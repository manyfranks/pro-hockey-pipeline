"""
Environment Signal

Evaluates situational factors: rest, travel, home/away.
Back-to-back games, long road trips, etc. affect performance.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class EnvironmentSignal(BaseSignal):
    """
    Detects environmental factors affecting performance.

    Methodology:
    - Back-to-back games (B2B) = fatigue = UNDER bias
    - Well-rested = positive
    - Home ice advantage = slight boost
    - Uses pipeline's situational analysis
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

        # Back-to-back penalty
        if is_b2b:
            adjustments.append(-0.3)
            notes.append("B2B fatigue")

        # Rest bonus/penalty
        if days_rest is not None:
            if days_rest >= 3:
                adjustments.append(0.1)
                notes.append(f"Well rested ({days_rest} days)")
            elif days_rest == 0:
                # Already captured by B2B, but add note
                pass

        # Home ice advantage (slight)
        if is_home is True:
            adjustments.append(0.05)
            notes.append("Home ice")
        elif is_home is False:
            adjustments.append(-0.03)

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
