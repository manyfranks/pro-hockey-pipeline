"""
Matchup Signal

Evaluates the quality of the opponent's goaltender and defense.
Weaker goalie / defense = OVER bias.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class MatchupSignal(BaseSignal):
    """
    Detects favorable/unfavorable goalie and team matchups.

    Methodology:
    - Goalie save % (below league avg = favorable)
    - Goalie GAA (above league avg = favorable)
    - Uses pipeline's goalie weakness assessment
    """

    # NHL league averages (2024-25 season)
    LEAGUE_AVG_SV_PCT = 0.905
    LEAGUE_AVG_GAA = 2.90

    # Thresholds
    ELITE_SV_PCT = 0.915
    WEAK_SV_PCT = 0.890
    ELITE_GAA = 2.20
    WEAK_GAA = 3.50

    @property
    def signal_type(self) -> str:
        return "matchup"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate matchup signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        goalie_name = ctx.opposing_goalie_name
        sv_pct = ctx.opposing_goalie_sv_pct
        gaa = ctx.opposing_goalie_gaa

        # Handle missing data
        if sv_pct is None and gaa is None:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.4,
                evidence="No goalie matchup data",
                raw_data={'reason': 'no_data'}
            )

        notes = []
        components = []

        # Save % component (50% weight)
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
            components.append(('sv_pct', sv_component, 0.5))

        # GAA component (30% weight)
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
            components.append(('gaa', gaa_component, 0.3))

        # Calculate weighted strength
        if components:
            total_weight = sum(c[2] for c in components)
            strength = sum(c[1] for c in components) / total_weight if total_weight else 0
            strength = max(-1.0, min(1.0, strength * 1.5))  # Scale up
        else:
            strength = 0.0

        # Confidence
        confidence = 0.85
        if sv_pct is None or gaa is None:
            confidence = 0.65

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
            }
        )
