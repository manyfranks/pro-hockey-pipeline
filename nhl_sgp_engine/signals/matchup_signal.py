"""
Matchup Signal

Evaluates the quality of the opponent's goaltender and defense.
Weaker goalie / defense = OVER bias.

Enhanced Dec 18, 2025 with NHL Edge API data:
- High-danger save %
- Recent form (L10 SV%)
- HOT/COLD/NEUTRAL assessment
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext

# Import NHL API for Edge data
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from providers.nhl_official_api import NHLOfficialAPI
    HAS_NHL_API = True
except ImportError:
    HAS_NHL_API = False


class MatchupSignal(BaseSignal):
    """
    Detects favorable/unfavorable goalie and team matchups.

    Methodology:
    - Goalie save % (below league avg = favorable)
    - Goalie GAA (above league avg = favorable)
    - Goalie recent form from Edge API (HOT/COLD/NEUTRAL)
    - High-danger save % from Edge API
    """

    # NHL league averages (2024-25 season)
    LEAGUE_AVG_SV_PCT = 0.905
    LEAGUE_AVG_GAA = 2.90

    # Thresholds
    ELITE_SV_PCT = 0.915
    WEAK_SV_PCT = 0.890
    ELITE_GAA = 2.20
    WEAK_GAA = 3.50

    # High-danger save % thresholds
    ELITE_HD_SV_PCT = 0.850
    WEAK_HD_SV_PCT = 0.800

    def __init__(self):
        """Initialize with NHL API if available."""
        self._nhl_api = NHLOfficialAPI() if HAS_NHL_API else None

    @property
    def signal_type(self) -> str:
        return "matchup"

    def _get_goalie_edge_data(self, goalie_id: Optional[int]) -> Optional[Dict]:
        """Fetch goalie Edge data from NHL API."""
        if not self._nhl_api or not goalie_id:
            return None
        try:
            return self._nhl_api.get_goalie_recent_form(goalie_id)
        except Exception:
            return None

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate matchup signal with Edge API enhancement."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        goalie_name = ctx.opposing_goalie_name
        sv_pct = ctx.opposing_goalie_sv_pct
        gaa = ctx.opposing_goalie_gaa

        # Try to get enhanced Edge data
        goalie_id = getattr(ctx, 'opposing_goalie_id', None)
        edge_data = self._get_goalie_edge_data(goalie_id)

        # Handle missing data
        if sv_pct is None and gaa is None and not edge_data:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.4,
                evidence="No goalie matchup data",
                raw_data={'reason': 'no_data'}
            )

        notes = []
        components = []

        # Save % component (40% weight - reduced to make room for Edge data)
        sv_component = 0.0
        if sv_pct is not None:
            if sv_pct < self.WEAK_SV_PCT:
                sv_component = 0.5  # Weak goalie = OVER
                notes.append(f"Weak SV% ({sv_pct:.3f})")
            elif sv_pct > self.ELITE_SV_PCT:
                sv_component = -0.5  # Elite goalie = UNDER
                notes.append(f"Elite SV% ({sv_pct:.3f})")
            else:
                # Linear scale between weak and elite
                sv_component = (self.LEAGUE_AVG_SV_PCT - sv_pct) / 0.025
                sv_component = max(-0.5, min(0.5, sv_component))
            components.append(('sv_pct', sv_component, 0.40))

        # GAA component (20% weight - reduced)
        gaa_component = 0.0
        if gaa is not None:
            if gaa > self.WEAK_GAA:
                gaa_component = 0.3  # High GAA = OVER
                notes.append(f"High GAA ({gaa:.2f})")
            elif gaa < self.ELITE_GAA:
                gaa_component = -0.3  # Low GAA = UNDER
                notes.append(f"Elite GAA ({gaa:.2f})")
            else:
                # Linear scale
                gaa_component = (gaa - self.LEAGUE_AVG_GAA) / 0.6
                gaa_component = max(-0.3, min(0.3, gaa_component))
            components.append(('gaa', gaa_component, 0.20))

        # =========================================================================
        # NEW: Edge API components (40% total weight)
        # =========================================================================
        if edge_data:
            # Recent Form component (20% weight)
            form_assessment = edge_data.get('form_assessment', 'NEUTRAL')
            form_component = 0.0
            if form_assessment == 'COLD':
                form_component = 0.4  # Cold goalie = OVER
                notes.append("Goalie COLD (L10)")
            elif form_assessment == 'HOT':
                form_component = -0.4  # Hot goalie = UNDER
                notes.append("Goalie HOT (L10)")
            components.append(('recent_form', form_component, 0.20))

            # High-Danger Save % component (20% weight)
            hd_sv_pct = edge_data.get('high_danger_sv_pct', 0)
            hd_component = 0.0
            if hd_sv_pct > 0:
                if hd_sv_pct < self.WEAK_HD_SV_PCT:
                    hd_component = 0.4  # Weak HD SV% = OVER
                    notes.append(f"Weak HD SV% ({hd_sv_pct:.3f})")
                elif hd_sv_pct > self.ELITE_HD_SV_PCT:
                    hd_component = -0.4  # Elite HD SV% = UNDER
                    notes.append(f"Elite HD SV% ({hd_sv_pct:.3f})")
                else:
                    # Linear scale
                    hd_component = (0.825 - hd_sv_pct) / 0.05
                    hd_component = max(-0.4, min(0.4, hd_component))
                components.append(('high_danger_sv', hd_component, 0.20))

        # Calculate weighted strength
        if components:
            total_weight = sum(c[2] for c in components)
            strength = sum(c[1] for c in components) / total_weight if total_weight else 0
            strength = max(-1.0, min(1.0, strength * 1.5))  # Scale up
        else:
            strength = 0.0

        # Confidence - boost when we have Edge data
        confidence = 0.85
        if sv_pct is None or gaa is None:
            confidence = 0.65
        if edge_data and edge_data.get('has_data'):
            confidence = min(0.95, confidence + 0.10)  # Boost for Edge data

        # Build evidence
        if goalie_name:
            goalie_str = f"vs {goalie_name}"
        else:
            goalie_str = f"vs {ctx.opponent} goalie"

        if strength > 0.2:
            quality = "vulnerable"
        elif strength < -0.2:
            quality = "strong"
        else:
            quality = "average"

        evidence = f"{goalie_str} ({quality})"
        if notes:
            evidence += f" - {', '.join(notes)}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'goalie_name': goalie_name,
                'sv_pct': sv_pct,
                'gaa': gaa,
                'components': {c[0]: c[1] for c in components},
                'edge_data': edge_data if edge_data else None,
            }
        )
