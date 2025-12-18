"""
Goalie Saves Signal

Evaluates goalie save props using:
- Opponent's shots on goal tendency (SOG/game)
- Goalie's recent form (save %, high-danger save %)
- Expected saves calculation vs prop line

Created: December 18, 2025
Uses: NHL Edge API goalie endpoints, team stats
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


class GoalieSavesSignal(BaseSignal):
    """
    Signal for goalie saves props (player_total_saves market).

    Methodology:
    1. Get opponent's average SOG per game
    2. Get goalie's recent save % and form
    3. Calculate expected saves: opponent_sog × goalie_save_pct
    4. Compare expected saves to prop line
    5. Adjust for home/away, opponent offensive zone time

    Positive strength = OVER bias (expect more saves)
    Negative strength = UNDER bias (expect fewer saves)
    """

    # League averages for normalization
    AVG_SOG_PER_GAME = 30.0  # ~30 shots per game league average
    AVG_SAVE_PCT = 0.905     # ~90.5% league average
    AVG_SAVES_PER_GAME = 27.0  # ~27 saves per game

    # Thresholds
    ELITE_SAVE_PCT = 0.920
    WEAK_SAVE_PCT = 0.890
    HIGH_WORKLOAD_SOG = 34.0
    LOW_WORKLOAD_SOG = 26.0

    def __init__(self):
        """Initialize with NHL API if available."""
        self._nhl_api = NHLOfficialAPI() if HAS_NHL_API else None
        self._team_stats_cache = {}

    @property
    def signal_type(self) -> str:
        return "goalie_saves"

    def _get_team_sog_stats(self, team_abbrev: str) -> Optional[Dict]:
        """Get team's shots on goal tendency."""
        if not self._nhl_api or not team_abbrev:
            return None

        # Check cache
        if team_abbrev in self._team_stats_cache:
            return self._team_stats_cache[team_abbrev]

        try:
            stats = self._nhl_api.get_team_stats(team_abbrev)
            skaters = stats.get('skaters', [])

            if not skaters:
                return None

            # Sum team totals
            total_shots = sum(s.get('shots', 0) for s in skaters)
            total_games = max(s.get('games_played', 0) for s in skaters) if skaters else 0

            if total_games == 0:
                return None

            result = {
                'team': team_abbrev,
                'total_shots': total_shots,
                'games_played': total_games,
                'sog_per_game': total_shots / total_games,
            }

            self._team_stats_cache[team_abbrev] = result
            return result

        except Exception:
            return None

    def _get_goalie_form(self, goalie_id: int) -> Optional[Dict]:
        """Get goalie's recent form data."""
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
        """Calculate goalie saves signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        # Only relevant for saves props
        if stat_type != 'saves':
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence=f"Goalie saves signal not relevant for {stat_type}",
                raw_data={'reason': 'irrelevant_stat'}
            )

        # Verify this is a goalie
        if ctx.position and ctx.position != 'G':
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence=f"Player is not a goalie (position: {ctx.position})",
                raw_data={'reason': 'not_goalie'}
            )

        notes = []
        components = []

        # Get opponent's SOG tendency
        opponent_sog_data = self._get_team_sog_stats(ctx.opponent) if ctx.opponent else None
        opponent_sog = opponent_sog_data.get('sog_per_game', self.AVG_SOG_PER_GAME) if opponent_sog_data else self.AVG_SOG_PER_GAME

        # Get goalie's form
        goalie_form = self._get_goalie_form(player_id)
        save_pct = self.AVG_SAVE_PCT
        form_assessment = 'NEUTRAL'

        if goalie_form:
            save_pct = goalie_form.get('recent_save_pct', 0) or goalie_form.get('season_save_pct', self.AVG_SAVE_PCT)
            form_assessment = goalie_form.get('form_assessment', 'NEUTRAL')

        # Calculate expected saves
        expected_saves = opponent_sog * save_pct

        # Component 1: Expected saves vs line (50% weight)
        saves_diff = expected_saves - line
        saves_diff_pct = saves_diff / line if line > 0 else 0

        # Map to signal strength: +10% diff = +0.5 strength
        line_component = min(1.0, max(-1.0, saves_diff_pct * 5))
        components.append(('expected_vs_line', line_component, 0.50))

        if saves_diff > 2:
            notes.append(f"Expected {expected_saves:.1f} saves vs line {line}")
        elif saves_diff < -2:
            notes.append(f"Expected only {expected_saves:.1f} saves vs line {line}")

        # Component 2: Opponent workload (25% weight)
        workload_component = 0.0
        if opponent_sog >= self.HIGH_WORKLOAD_SOG:
            workload_component = 0.5
            notes.append(f"High-volume opponent ({opponent_sog:.1f} SOG/game)")
        elif opponent_sog <= self.LOW_WORKLOAD_SOG:
            workload_component = -0.5
            notes.append(f"Low-volume opponent ({opponent_sog:.1f} SOG/game)")
        else:
            # Linear scale between thresholds
            workload_component = (opponent_sog - self.AVG_SOG_PER_GAME) / (self.HIGH_WORKLOAD_SOG - self.AVG_SOG_PER_GAME)
            workload_component = min(0.5, max(-0.5, workload_component))
        components.append(('opponent_workload', workload_component, 0.25))

        # Component 3: Goalie form (25% weight)
        form_component = 0.0
        if form_assessment == 'HOT':
            form_component = 0.4
            notes.append(f"Goalie HOT (SV% {save_pct:.3f})")
        elif form_assessment == 'COLD':
            form_component = -0.4
            notes.append(f"Goalie COLD (SV% {save_pct:.3f})")
        else:
            # Use save % relative to average
            if save_pct >= self.ELITE_SAVE_PCT:
                form_component = 0.3
            elif save_pct <= self.WEAK_SAVE_PCT:
                form_component = -0.3
        components.append(('goalie_form', form_component, 0.25))

        # Calculate weighted strength
        if components:
            total_weight = sum(c[2] for c in components)
            strength = sum(c[1] * c[2] for c in components) / total_weight if total_weight else 0
            strength = max(-1.0, min(1.0, strength))
        else:
            strength = 0.0

        # Confidence based on data availability
        confidence = 0.75
        if not opponent_sog_data:
            confidence -= 0.15
        if not goalie_form or form_assessment == 'NEUTRAL':
            confidence -= 0.10

        # Build evidence
        direction = "OVER" if strength > 0.1 else "UNDER" if strength < -0.1 else "neutral"
        evidence = f"Expected {expected_saves:.1f} saves (opp {opponent_sog:.1f} SOG × {save_pct:.3f} SV%)"
        if notes:
            evidence += f" - {', '.join(notes[:2])}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'expected_saves': expected_saves,
                'prop_line': line,
                'opponent_sog': opponent_sog,
                'goalie_save_pct': save_pct,
                'form_assessment': form_assessment,
                'saves_diff': saves_diff,
                'components': {c[0]: c[1] for c in components},
            }
        )
