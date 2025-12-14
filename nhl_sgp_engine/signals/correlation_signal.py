"""
Correlation Signal

Evaluates how game-level factors (total, spread) correlate with player props.
High game total = more scoring opportunities for top players.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class CorrelationSignal(BaseSignal):
    """
    Detects correlations between game context and player props.

    Methodology:
    - High game total (O/U) = more scoring = OVER for top players
    - Low game total = defensive game = UNDER bias
    - Favorite status = more offensive zone time
    """

    # Reference points
    HIGH_TOTAL = 6.5   # Above this is high-scoring game
    LOW_TOTAL = 5.5    # Below this is low-scoring game
    AVG_TOTAL = 6.0

    @property
    def signal_type(self) -> str:
        return "correlation"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate correlation signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        game_total = ctx.game_total
        spread = ctx.spread
        line_number = ctx.line_number

        notes = []
        strength = 0.0

        # Handle missing data
        if game_total is None:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.4,
                evidence="No game total data",
                raw_data={'reason': 'no_data'}
            )

        # Game total impact
        total_deviation = game_total - self.AVG_TOTAL

        # For points/goals props:
        # High total = more scoring opportunities
        # But effect is stronger for top-line players
        if stat_type in ['points', 'goals', 'assists']:
            # Base correlation
            total_impact = total_deviation * 0.15  # 15% per goal above/below avg

            # Amplify for top players
            if line_number and line_number <= 2:
                total_impact *= 1.3
                notes.append(f"Top-6 gets more in {'high' if total_deviation > 0 else 'low'}-scoring")

            strength += total_impact

            if game_total >= self.HIGH_TOTAL:
                notes.append(f"High total ({game_total})")
            elif game_total <= self.LOW_TOTAL:
                notes.append(f"Low total ({game_total})")

        # Spread impact (being favorite = more offensive zone time)
        if spread is not None:
            # Negative spread = favorite
            if spread < -1.5:
                strength += 0.1
                notes.append("Heavy favorite")
            elif spread > 1.5:
                strength -= 0.05
                notes.append("Underdog")

        # Cap strength
        strength = max(-1.0, min(1.0, strength))

        # Confidence (game lines are usually accurate)
        confidence = 0.70

        # Build evidence
        if notes:
            evidence = " - ".join(notes)
        else:
            evidence = f"Neutral game context (total {game_total})"

        # Add correlation description
        if strength > 0.1:
            corr_desc = f"correlates +{abs(strength)*100:.0f}%"
        elif strength < -0.1:
            corr_desc = f"correlates -{abs(strength)*100:.0f}%"
        else:
            corr_desc = "minimal correlation"

        evidence = f"{evidence} ({corr_desc} with {stat_type})"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'game_total': game_total,
                'spread': spread,
                'line_number': line_number,
                'total_deviation': total_deviation,
            }
        )
