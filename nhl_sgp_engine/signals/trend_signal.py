"""
Trend Signal

Compares recent performance to season average.
Detects hot/cold streaks that may not be reflected in season averages.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class TrendSignal(BaseSignal):
    """
    Detects recent performance trends.

    Methodology:
    - Compare recent PPG (from pipeline) to season average
    - Hot streaks (recent > season) = OVER bias
    - Cold streaks (recent < season) = UNDER bias
    - Point streaks provide additional confidence
    """

    @property
    def signal_type(self) -> str:
        return "trend"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate trend signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        # Get recent vs season data (convert Decimals to float)
        recent_ppg = float(ctx.recent_ppg) if ctx.recent_ppg is not None else None
        season_avg = ctx.get_season_avg('points')  # Use points as proxy
        if season_avg is not None:
            season_avg = float(season_avg)
        point_streak = ctx.point_streak or 0
        recent_games = ctx.recent_games or 0

        # Handle missing data
        if recent_ppg is None or season_avg is None or season_avg == 0:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence="Insufficient trend data",
                raw_data={'reason': 'no_data'}
            )

        # Calculate trend direction
        # Positive = trending up, Negative = trending down
        pct_change = (recent_ppg - season_avg) / season_avg

        # Map to strength
        # 30% above season = strong hot streak
        strength = max(-1.0, min(1.0, pct_change / 0.3))

        # Adjust confidence based on sample and streak
        base_confidence = 0.7

        # Streak bonus
        if point_streak >= 5:
            base_confidence += 0.15
            streak_note = f" ({point_streak}-game point streak)"
        elif point_streak >= 3:
            base_confidence += 0.08
            streak_note = f" ({point_streak}-game streak)"
        else:
            streak_note = ""

        # Sample size adjustment
        if recent_games < 5:
            base_confidence -= 0.2

        confidence = max(0.3, min(0.95, base_confidence))

        # Build evidence
        direction = "UP" if pct_change > 0 else "DOWN"
        pct_str = f"{abs(pct_change)*100:.1f}%"
        evidence = f"L{recent_games} avg {recent_ppg:.2f} vs season {season_avg:.2f} ({direction} {pct_str}){streak_note}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'recent_ppg': recent_ppg,
                'season_avg': season_avg,
                'pct_change': pct_change,
                'point_streak': point_streak,
                'recent_games': recent_games,
            }
        )
