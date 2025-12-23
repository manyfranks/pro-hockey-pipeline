"""
Edge Calculator for NHL SGP Engine

Combines signals and compares to market implied probability
to identify betting edges.
"""
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
import math

from ..signals import (
    SignalResult,
    PropContext,
    LineValueSignal,
    TrendSignal,
    UsageSignal,
    MatchupSignal,
    EnvironmentSignal,
    CorrelationSignal,
    ShotQualitySignal,
    GoalieSavesSignal,
    GameTotalsSignal,
)
from ..config.settings import SIGNAL_WEIGHTS, MIN_EDGE_PCT


@dataclass
class EdgeResult:
    """Result of edge calculation for a prop."""
    # Prop identification
    player_name: str
    stat_type: str
    line: float

    # Model vs Market
    model_probability: float
    market_probability: float
    edge_pct: float

    # Direction
    direction: str  # 'over' or 'under'

    # Confidence
    confidence: float
    primary_reason: str
    supporting_reasons: List[str]
    risk_factors: List[str]

    # Signals breakdown
    signals: Dict[str, Dict]

    # Combined score
    weighted_signal: float

    # Contrarian mode tracking
    contrarian_applied: bool = False
    original_direction: Optional[str] = None  # Direction before fading

    def has_edge(self, min_edge: float = MIN_EDGE_PCT) -> bool:
        """Check if this prop has a meaningful edge."""
        return abs(self.edge_pct) >= min_edge

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class EdgeCalculator:
    """
    Calculates edges by comparing model signals to market odds.

    Process:
    1. Calculate all 6 signals for the prop
    2. Combine signals using weights
    3. Convert to model probability
    4. Compare to market implied probability
    5. Calculate edge %
    6. (Optional) Apply contrarian logic for high-edge predictions
    """

    # Stat-specific contrarian thresholds (Dec 22, 2025 optimization)
    #
    # BACKTEST FINDINGS (Nov-Dec 2025):
    #
    # saves (947 props):
    #   - 52.6% overall, negative edge = 55.0%, 5-10% edge = 41.8%
    #   - Threshold: 5.0% - fade OVER/UNDER at 5%+ edge
    #
    # assists (9,720 props):
    #   - Natural OVER rate: 35.1% (at 0.5 line, ~1/3 players get an assist)
    #   - Model OVER picks: 38.3% (+3.2% above base) - model has slight edge
    #   - BUT: 10%+ edge OVER picks hit only 36.1% (barely above base rate)
    #   - Fading 5%+ edge OVER picks: 63.7% win rate (+13.7% edge!)
    #   - Threshold: 5.0% - fade high-confidence OVER picks
    #
    # goals: Lines are 1.5/2.5 where UNDER wins 98%+ naturally. Model OVER picks
    #        hit 25% vs 1.4% base rate - model is WORKING, not inverted!
    #
    # points: 50.6% hit rate at 0-5% edge (genuinely best bucket)
    # shots_on_goal: Similar pattern to points
    #
    STAT_CONTRARIAN_THRESHOLDS = {
        'goals': 15.0,        # Standard - model works well for rare event
        'saves': 5.0,         # Validated: 55% neg edge vs 41.8% at 5-10%
        'assists': 5.0,       # Validated: Fade 5%+ OVER → 63.7% win rate
        'points': 15.0,       # Validated: Less edge (~5.5%), keep conservative
        'shots_on_goal': 10.0, # Validated: Fade 10%+ OVER → 59.6% win rate
    }

    # Direction overrides - not needed after proper backtest analysis
    # Only use if data shows extreme directional bias (>70% one direction)
    DIRECTION_OVERRIDE = {
        # No overrides - saves shows balanced 52.6% hit rate, no extreme bias
    }

    def __init__(
        self,
        signal_weights: Dict[str, float] = None,
        contrarian_threshold: Optional[float] = None,
        stat_contrarian_thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize EdgeCalculator.

        Args:
            signal_weights: Custom weights for signals (default: SIGNAL_WEIGHTS)
            contrarian_threshold: Default threshold for fading high-edge predictions.
                                  Based on backtest findings:
                                  - 15%+ edge = 42.8% hit rate
                                  - Fading 15%+ edge = ~57.2% hit rate
                                  Recommended: 10.0 to 15.0
            stat_contrarian_thresholds: Optional dict of stat_type -> threshold for
                                        stat-specific contrarian behavior. Useful when
                                        certain markets (like saves) benefit from more
                                        aggressive fading.
        """
        self.weights = signal_weights or SIGNAL_WEIGHTS
        self.contrarian_threshold = contrarian_threshold
        self.stat_contrarian_thresholds = stat_contrarian_thresholds or self.STAT_CONTRARIAN_THRESHOLDS

        # Initialize signals
        self.signals = {
            'line_value': LineValueSignal(),
            'trend': TrendSignal(),
            'usage': UsageSignal(),
            'matchup': MatchupSignal(),
            'environment': EnvironmentSignal(),
            'correlation': CorrelationSignal(),
            'shot_quality': ShotQualitySignal(),  # NHL Edge API - skater data
            'goalie_saves': GoalieSavesSignal(),  # NHL Edge API - goalie saves
            'game_totals': GameTotalsSignal(),    # Game total O/U
        }

    def american_to_probability(self, odds: int) -> float:
        """
        Convert American odds to implied probability.

        Examples:
            -110 -> 0.524 (52.4%)
            +150 -> 0.400 (40.0%)
        """
        if odds == 0:
            return 0.5

        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def probability_to_american(self, prob: float) -> int:
        """Convert probability to American odds."""
        if prob <= 0 or prob >= 1:
            return 0

        if prob >= 0.5:
            return int(-100 * prob / (1 - prob))
        else:
            return int(100 * (1 - prob) / prob)

    def signal_to_probability(
        self,
        weighted_signal: float,
        base_probability: float = 0.5,
    ) -> float:
        """
        Convert weighted signal strength to probability.

        Args:
            weighted_signal: Combined signal (-1 to +1)
            base_probability: Starting point (usually 0.5)

        Returns:
            Probability (0-1)
        """
        # Use logistic function to map signal to probability
        # weighted_signal of 0 -> base_probability
        # weighted_signal of +1 -> ~0.69 (at base 0.5, with 0.8 scaling)
        # weighted_signal of -1 -> ~0.31 (at base 0.5, with 0.8 scaling)

        # Convert base to logit
        if base_probability <= 0:
            base_probability = 0.01
        if base_probability >= 1:
            base_probability = 0.99

        base_logit = math.log(base_probability / (1 - base_probability))

        # BACKTEST FINDINGS (Dec 18, 2025 - 42,377 props):
        # - +1.5x: 48.3% overall, 0-5% edge = 50.6%, 15%+ = 42.8% (BEST)
        # - +0.8x: 45.4% overall, 15%+ = 36.0% (WORSE)
        # - -1.5x: 43.5% overall, 15%+ = 39.0% (WORST)
        #
        # Edge buckets are INVERTED regardless of scaling factor.
        # Root cause is likely signal combination logic, not scaling.
        # Reverting to +1.5x as it has best overall hit rate.
        # TODO: Investigate individual signal isolation and contrarian logic.
        adjusted_logit = base_logit + (weighted_signal * 1.5)

        # Convert back to probability
        prob = 1 / (1 + math.exp(-adjusted_logit))

        return prob

    def calculate_edge(
        self,
        ctx: PropContext,
        over_odds: int,
        under_odds: int,
    ) -> EdgeResult:
        """
        Calculate edge for a player prop.

        Args:
            ctx: PropContext with all player/game data
            over_odds: American odds for the over
            under_odds: American odds for the under

        Returns:
            EdgeResult with edge analysis
        """
        # Calculate all signals
        signal_results = {}
        for name, signal in self.signals.items():
            result = signal.calculate(
                player_id=ctx.player_id,
                player_name=ctx.player_name,
                stat_type=ctx.stat_type,
                line=ctx.line,
                game_context=ctx,
            )
            signal_results[name] = result

        # Calculate weighted signal
        weighted_signal = 0.0
        total_weight = 0.0

        for name, result in signal_results.items():
            weight = self.weights.get(name, 0.1)
            # Weight by both signal weight and confidence
            effective_weight = weight * result.confidence
            weighted_signal += result.strength * effective_weight
            total_weight += effective_weight

        if total_weight > 0:
            weighted_signal = weighted_signal / total_weight

        # Get market probabilities
        over_prob = self.american_to_probability(over_odds) if over_odds else 0.5
        under_prob = self.american_to_probability(under_odds) if under_odds else 0.5

        # If we only have one side, estimate the other
        if over_odds and not under_odds:
            under_prob = 1 - over_prob + 0.05  # Add ~5% vig
        elif under_odds and not over_odds:
            over_prob = 1 - under_prob + 0.05

        # Convert weighted signal to model probability
        # Positive signal = OVER bias
        model_prob_over = self.signal_to_probability(weighted_signal, 0.5)
        model_prob_under = 1 - model_prob_over

        # Calculate edges
        over_edge = (model_prob_over - over_prob) * 100
        under_edge = (model_prob_under - under_prob) * 100

        # Determine best direction (before contrarian logic)
        if over_edge >= under_edge:
            direction = 'over'
            edge_pct = over_edge
            market_prob = over_prob
            model_prob = model_prob_over
        else:
            direction = 'under'
            edge_pct = under_edge
            market_prob = under_prob
            model_prob = model_prob_under

        # DIRECTION OVERRIDE (Dec 22, 2025)
        # Some markets have extreme directional bias in backtests
        # e.g., saves: 100% under hit rate, 0% over hit rate
        stat_type = ctx.stat_type if hasattr(ctx, 'stat_type') else ''
        if stat_type in self.DIRECTION_OVERRIDE:
            forced_direction = self.DIRECTION_OVERRIDE[stat_type]
            if direction != forced_direction:
                # Force to the override direction
                direction = forced_direction
                if forced_direction == 'under':
                    edge_pct = under_edge
                    market_prob = under_prob
                    model_prob = model_prob_under
                else:
                    edge_pct = over_edge
                    market_prob = over_prob
                    model_prob = model_prob_over

        # Apply contrarian logic if threshold is set and edge exceeds it
        # BACKTEST INSIGHT (Dec 22, 2025):
        # - goals: 80.9% hit rate on negative edge → threshold 0% (always fade)
        # - saves: 63.2% hit rate on negative edge → threshold 0% (always fade)
        # - assists: 59.5% hit rate on negative edge → threshold 5%
        # - points: 50.6% hit rate at 0-5% edge → threshold 15%
        original_direction = direction

        # Get stat-specific threshold, fallback to default
        # (stat_type already extracted above for direction override)
        effective_threshold = self.stat_contrarian_thresholds.get(
            stat_type,
            self.contrarian_threshold  # Fallback to default threshold
        )

        # Note: use `is not None` because threshold can be 0.0 for always-fade markets
        if effective_threshold is not None and edge_pct > effective_threshold:
            # Flip the direction
            if direction == 'over':
                direction = 'under'
                edge_pct = under_edge
                market_prob = under_prob
                model_prob = model_prob_under
            else:
                direction = 'over'
                edge_pct = over_edge
                market_prob = over_prob
                model_prob = model_prob_over

            # Note: After fading, we're betting WITH the market direction
            # The "edge" is now the market's implicit edge against our original model

        # Build reasons
        primary_reason, supporting, risks = self._build_reasons(signal_results, direction)

        # Calculate overall confidence
        confidences = [r.confidence for r in signal_results.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        # Determine if contrarian logic was applied
        contrarian_applied = (
            self.contrarian_threshold is not None
            and original_direction != direction
        )

        return EdgeResult(
            player_name=ctx.player_name,
            stat_type=ctx.stat_type,
            line=ctx.line,
            model_probability=model_prob,
            market_probability=market_prob,
            edge_pct=edge_pct,
            direction=direction,
            confidence=avg_confidence,
            primary_reason=primary_reason,
            supporting_reasons=supporting,
            risk_factors=risks,
            signals={name: result.to_dict() for name, result in signal_results.items()},
            weighted_signal=weighted_signal,
            contrarian_applied=contrarian_applied,
            original_direction=original_direction if contrarian_applied else None,
        )

    def _build_reasons(
        self,
        signal_results: Dict[str, SignalResult],
        direction: str,
    ) -> tuple:
        """Build primary reason, supporting reasons, and risk factors."""

        # Sort signals by absolute strength * confidence
        ranked = sorted(
            signal_results.items(),
            key=lambda x: abs(x[1].strength) * x[1].confidence,
            reverse=True
        )

        primary_reason = ""
        supporting = []
        risks = []

        for name, result in ranked:
            # Determine if signal supports the direction
            if direction == 'over':
                supports = result.strength > 0.1
                opposes = result.strength < -0.1
            else:
                supports = result.strength < -0.1
                opposes = result.strength > 0.1

            if supports:
                if not primary_reason:
                    primary_reason = result.evidence
                else:
                    supporting.append(result.evidence)
            elif opposes:
                risks.append(f"{name.replace('_', ' ').title()}: {result.evidence}")

        if not primary_reason:
            primary_reason = "No strong signals detected"

        return primary_reason, supporting[:3], risks[:2]


def calculate_edge_for_prop(
    player_name: str,
    stat_type: str,
    line: float,
    over_odds: int,
    under_odds: int,
    context: Dict[str, Any],
) -> EdgeResult:
    """
    Convenience function to calculate edge for a single prop.

    Args:
        player_name: Player's full name
        stat_type: 'points', 'goals', etc.
        line: Prop line (0.5, 1.5, etc.)
        over_odds: American odds for over
        under_odds: American odds for under
        context: Dict with player/game context

    Returns:
        EdgeResult
    """
    calculator = EdgeCalculator()

    # Build PropContext
    ctx = PropContext(
        player_id=context.get('player_id', 0),
        player_name=player_name,
        team=context.get('team', ''),
        position=context.get('position', ''),
        stat_type=stat_type,
        line=line,
        game_id=context.get('game_id', ''),
        game_date=context.get('game_date', ''),
        opponent=context.get('opponent', ''),
        is_home=context.get('is_home', False),
        **{k: v for k, v in context.items() if k not in [
            'player_id', 'team', 'position', 'game_id',
            'game_date', 'opponent', 'is_home'
        ]}
    )

    return calculator.calculate_edge(ctx, over_odds, under_odds)
