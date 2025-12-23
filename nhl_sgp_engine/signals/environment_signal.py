"""
Environment Signal

Evaluates situational factors: rest, travel, home/away.
Back-to-back games, long road trips, etc. affect performance.

Dec 22, 2025: Scaled up adjustments to use full [-1, +1] range.
Previously max positive was +0.05 which hit the 0.05 threshold boundary
and was classified as neutral in backtest analysis.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class EnvironmentSignal(BaseSignal):
    """
    Detects environmental factors affecting performance.

    Methodology:
    - Back-to-back games (B2B) = fatigue = UNDER bias
    - Well-rested = positive
    - Home ice advantage = moderate boost
    - Uses pipeline's situational analysis

    Output range: [-1.0 to +0.5] approximately
    - B2B + away: -0.9 + (-0.1) = -1.0
    - Well rested + home: +0.3 + +0.2 = +0.5
    """

    @property
    def signal_type(self) -> str:
        return "environment"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate environment signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        is_b2b = ctx.is_b2b
        days_rest = ctx.days_rest
        is_home = ctx.is_home

        notes = []
        adjustments = []

        # Back-to-back penalty (SCALED UP from -0.3)
        # B2B is significant - players average 5-10% fewer points on B2B
        if is_b2b:
            adjustments.append(-0.9)
            notes.append("B2B fatigue")

        # Rest bonus/penalty (SCALED UP from +0.1)
        if days_rest is not None:
            if days_rest >= 3:
                adjustments.append(0.3)
                notes.append(f"Well rested ({days_rest} days)")
            elif days_rest == 0:
                # Already captured by B2B, but add note
                pass

        # Home ice advantage (SCALED UP from +0.05/-0.03)
        # Home teams win ~55% of NHL games, meaningful edge
        if is_home is True:
            adjustments.append(0.2)
            notes.append("Home ice")
        elif is_home is False:
            adjustments.append(-0.1)
            notes.append("Away")

        # Calculate total adjustment
        strength = sum(adjustments) if adjustments else 0
        strength = max(-1.0, min(1.0, strength))

        # Confidence
        confidence = 0.8
        if is_b2b is None and days_rest is None:
            confidence = 0.5

        # Build evidence
        if notes:
            evidence = ", ".join(notes)
        else:
            evidence = "Normal schedule"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'is_b2b': is_b2b,
                'days_rest': days_rest,
                'is_home': is_home,
                'adjustments': adjustments,
            }
        )
