"""
Shot Quality Signal

Evaluates player's shot quality and offensive zone deployment using NHL Edge data.
Higher shot speed + more high-danger shots + more offensive zone time = OVER bias.

Created: December 18, 2025
Uses: NHL Edge API skater endpoints
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


class ShotQualitySignal(BaseSignal):
    """
    Detects shot quality and offensive opportunity using NHL Edge data.

    Methodology:
    - Shot speed (faster = more likely to score)
    - High-danger shot % (shooting from better locations)
    - Offensive zone time % (more time in attacking zone)
    - Offensive zone starts % (favorable deployment)

    Best for: player_goals, player_shots_on_goal
    """

    # Thresholds based on NHL averages
    ELITE_SHOT_SPEED = 95.0  # mph
    WEAK_SHOT_SPEED = 80.0

    ELITE_HD_PCT = 0.40  # 40% of shots from high-danger
    WEAK_HD_PCT = 0.20

    ELITE_OZ_PCT = 55.0  # 55% offensive zone time
    WEAK_OZ_PCT = 45.0

    def __init__(self):
        """Initialize with NHL API if available."""
        self._nhl_api = NHLOfficialAPI() if HAS_NHL_API else None

    @property
    def signal_type(self) -> str:
        return "shot_quality"

    def _get_skater_edge_data(self, player_id: int) -> Optional[Dict]:
        """Fetch skater Edge data from NHL API."""
        if not self._nhl_api or not player_id:
            return None
        try:
            return self._nhl_api.get_skater_edge_summary(player_id)
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
        """Calculate shot quality signal using Edge data."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        # Only relevant for scoring/shooting props
        if stat_type not in ['goals', 'shots_on_goal', 'points']:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence=f"Shot quality not relevant for {stat_type}",
                raw_data={'reason': 'irrelevant_stat'}
            )

        # Get Edge data
        edge_data = self._get_skater_edge_data(player_id)

        if not edge_data or not edge_data.get('has_data'):
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.4,
                evidence="No Edge data available",
                raw_data={'reason': 'no_edge_data'}
            )

        notes = []
        components = []

        # Shot Quality Assessment (40% weight)
        shot_quality = edge_data.get('shot_quality', 'AVERAGE')
        sq_component = 0.0
        if shot_quality == 'HIGH':
            sq_component = 0.4
            notes.append("High shot quality")
        elif shot_quality == 'LOW':
            sq_component = -0.4
            notes.append("Low shot quality")
        components.append(('shot_quality', sq_component, 0.40))

        # High-Danger Shot % (30% weight)
        hd_pct = edge_data.get('high_danger_shot_pct', 0)
        hd_component = 0.0
        if hd_pct >= self.ELITE_HD_PCT:
            hd_component = 0.4
            notes.append(f"Elite HD% ({hd_pct:.1%})")
        elif hd_pct <= self.WEAK_HD_PCT:
            hd_component = -0.4
            notes.append(f"Weak HD% ({hd_pct:.1%})")
        else:
            # Linear scale
            hd_component = (hd_pct - 0.30) / 0.10
            hd_component = max(-0.4, min(0.4, hd_component))
        components.append(('high_danger_pct', hd_component, 0.30))

        # Zone Deployment Assessment (30% weight)
        zone_deploy = edge_data.get('zone_deployment', 'BALANCED')
        zd_component = 0.0
        if zone_deploy == 'OFFENSIVE':
            zd_component = 0.3
            notes.append("Offensive deployment")
        elif zone_deploy == 'DEFENSIVE':
            zd_component = -0.3
            notes.append("Defensive deployment")
        components.append(('zone_deployment', zd_component, 0.30))

        # Calculate weighted strength
        if components:
            total_weight = sum(c[2] for c in components)
            strength = sum(c[1] for c in components) / total_weight if total_weight else 0
            strength = max(-1.0, min(1.0, strength * 1.5))  # Scale up
        else:
            strength = 0.0

        # Confidence - lower since this is supplementary
        confidence = 0.70

        # Build evidence
        if strength > 0.2:
            quality = "favorable"
        elif strength < -0.2:
            quality = "unfavorable"
        else:
            quality = "average"

        evidence = f"Shot quality {quality}"
        if notes:
            evidence += f" - {', '.join(notes)}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'shot_quality': shot_quality,
                'high_danger_pct': hd_pct,
                'zone_deployment': zone_deploy,
                'top_shot_speed': edge_data.get('top_shot_speed', 0),
                'offensive_zone_pct': edge_data.get('offensive_zone_pct', 0),
                'components': {c[0]: c[1] for c in components},
            }
        )
