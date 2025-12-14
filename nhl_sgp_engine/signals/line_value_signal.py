"""
Line Value Signal

Compares player's season/recent average to the prop line.
This is the PRIMARY signal (35% weight) - if a player averages 1.2 PPG
and the line is 0.5 points, that's a strong OVER signal.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class LineValueSignal(BaseSignal):
    """
    Detects value by comparing player averages to prop lines.

    Methodology:
    - Calculate player's average for the stat type
    - Compare to the prop line
    - Larger deviation = stronger signal
    """

    @property
    def signal_type(self) -> str:
        return "line_value"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate line value signal."""

        # Get context
        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        # Calculate season average
        season_avg = ctx.get_season_avg(stat_type)

        if season_avg is None:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence=f"No season data for {stat_type}",
                raw_data={'reason': 'no_data'}
            )

        # Calculate deviation
        # Positive = over (avg > line), Negative = under (avg < line)
        if line > 0:
            pct_diff = (season_avg - line) / line
        else:
            pct_diff = season_avg - line  # For 0.5 lines

        # Map to strength (-1 to 1)
        # 50% above line = +1.0, 50% below = -1.0
        strength = max(-1.0, min(1.0, pct_diff / 0.5))

        # Confidence based on sample size
        games = ctx.season_games or 0
        if games >= 20:
            confidence = 0.90
        elif games >= 10:
            confidence = 0.80
        elif games >= 5:
            confidence = 0.65
        else:
            confidence = 0.40

        # Build evidence
        direction = "ABOVE" if season_avg > line else "BELOW"
        pct_str = f"{abs(pct_diff)*100:.0f}%"
        evidence = f"Season avg {season_avg:.2f} is {pct_str} {direction} line {line}"

        # Add edge indicator
        if abs(pct_diff) >= 0.5:
            evidence += " (strong edge)"
        elif abs(pct_diff) >= 0.25:
            evidence += " (moderate edge)"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'season_avg': season_avg,
                'line': line,
                'pct_diff': pct_diff,
                'games_sample': games,
            }
        )
