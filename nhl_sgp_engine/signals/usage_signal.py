"""
Usage Signal

Detects changes in player deployment/opportunity.
Line changes, PP time, TOI trends affect scoring opportunity.
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext


class UsageSignal(BaseSignal):
    """
    Detects usage/opportunity changes.

    Methodology:
    - Line number: 1st line >> 4th line
    - PP unit: PP1 >> PP2 >> None
    - TOI: More ice time = more chances
    - Changes from typical deployment
    """

    # Reference benchmarks (NHL averages)
    LINE_SCORES = {1: 1.0, 2: 0.70, 3: 0.40, 4: 0.15}
    PP_BONUSES = {1: 0.30, 2: 0.15, 0: 0.0}
    ELITE_TOI = 22.0  # Elite forward TOI
    AVG_TOI = 15.0    # Average forward TOI

    @property
    def signal_type(self) -> str:
        return "usage"

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate usage signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        line_number = ctx.line_number
        pp_unit = ctx.pp_unit or 0
        toi = ctx.avg_toi_minutes

        notes = []

        # Handle missing data
        if line_number is None:
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.4,
                evidence="No deployment data available",
                raw_data={'reason': 'no_data'}
            )

        # Calculate base opportunity score
        line_score = self.LINE_SCORES.get(line_number, 0.15)
        pp_bonus = self.PP_BONUSES.get(pp_unit, 0.0)

        # TOI factor
        toi_factor = 0.0
        if toi:
            if toi >= self.ELITE_TOI:
                toi_factor = 0.2
                notes.append(f"Elite TOI ({toi:.1f}min)")
            elif toi >= self.AVG_TOI:
                toi_factor = 0.1
            elif toi < 12:
                toi_factor = -0.2
                notes.append(f"Limited TOI ({toi:.1f}min)")

        # Combined opportunity score (0-1.5 range)
        opportunity = line_score + pp_bonus + toi_factor

        # Map to strength (-1 to 1)
        # High opportunity (>0.9) = positive, Low (<0.5) = negative
        # Neutral = 0.7 (2nd line, no PP)
        neutral_point = 0.7
        strength = (opportunity - neutral_point) / 0.6
        strength = max(-1.0, min(1.0, strength))

        # Confidence based on data quality
        confidence = 0.85
        if toi is None:
            confidence -= 0.15

        # Build evidence
        line_desc = f"Line {line_number}"
        if pp_unit == 1:
            pp_desc = " + PP1"
        elif pp_unit == 2:
            pp_desc = " + PP2"
        else:
            pp_desc = ""

        if strength > 0.3:
            trend = "ELEVATED"
        elif strength < -0.3:
            trend = "LIMITED"
        else:
            trend = "STABLE"

        evidence = f"{line_desc}{pp_desc} deployment ({trend})"
        if notes:
            evidence += f" - {', '.join(notes)}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'line_number': line_number,
                'pp_unit': pp_unit,
                'toi': toi,
                'opportunity_score': opportunity,
            }
        )
