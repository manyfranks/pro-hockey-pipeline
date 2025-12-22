"""
Goalie Saves Signal - OPTIMIZED VERSION

Evaluates goalie save props using:
- Opponent's offensive zone time % (NHL Edge API) - correlates with shots generated
- Game total correlation (higher totals = more saves opportunities)
- Opponent's shots on goal tendency (SOG/game)
- Goalie's recent form (save %, high-danger save %)
- Expected saves calculation vs prop line

CRITICAL OPTIMIZATION (Dec 22, 2025):
- Backtest showed 63.2% hit rate on NEGATIVE edge for saves
- This means the signal direction was INVERTED
- Signal now outputs INVERTED polarity to align with empirical data
- Positive strength = UNDER bias (contrarian to naive expectation)
- Negative strength = OVER bias (contrarian to naive expectation)

Created: December 18, 2025
Updated: December 22, 2025 - Added zone time, game total correlation, inverted polarity
Uses: NHL Edge API goalie endpoints, team zone time, team stats
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

    OPTIMIZED METHODOLOGY (Dec 22, 2025):
    1. Get opponent's offensive zone time % (NHL Edge API) - key predictor
    2. Get opponent's average SOG per game
    3. Get goalie's recent save % and form
    4. Factor in game total correlation (higher totals = more saves)
    5. Calculate expected saves: opponent_sog × goalie_save_pct
    6. Compare expected saves to prop line
    7. INVERT the signal (63.2% hit rate on negative edge)

    INVERTED POLARITY (based on backtest findings):
    - Raw positive signal (expect more saves) → OUTPUT NEGATIVE (bet UNDER)
    - Raw negative signal (expect fewer saves) → OUTPUT POSITIVE (bet OVER)

    This inversion aligns with the 63.2% hit rate on negative edge finding.
    """

    # League averages for normalization
    AVG_SOG_PER_GAME = 30.0  # ~30 shots per game league average
    AVG_SAVE_PCT = 0.905     # ~90.5% league average
    AVG_SAVES_PER_GAME = 27.0  # ~27 saves per game
    AVG_OZ_TIME_PCT = 33.0   # ~33% offensive zone time (balanced)
    AVG_GAME_TOTAL = 6.0     # ~6 goals per game

    # Thresholds
    ELITE_SAVE_PCT = 0.920
    WEAK_SAVE_PCT = 0.890
    HIGH_WORKLOAD_SOG = 34.0
    LOW_WORKLOAD_SOG = 26.0
    HIGH_OZ_TIME = 38.0      # Teams that dominate possession
    LOW_OZ_TIME = 28.0       # Teams that struggle to maintain possession

    def __init__(self):
        """Initialize with NHL API if available."""
        self._nhl_api = NHLOfficialAPI() if HAS_NHL_API else None
        self._team_stats_cache = {}
        self._zone_time_cache = {}

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
            total_goals = sum(s.get('goals', 0) for s in skaters)
            total_games = max(s.get('games_played', 0) for s in skaters) if skaters else 0

            if total_games == 0:
                return None

            result = {
                'team': team_abbrev,
                'total_shots': total_shots,
                'total_goals': total_goals,
                'games_played': total_games,
                'sog_per_game': total_shots / total_games,
                'goals_per_game': total_goals / total_games,
            }

            self._team_stats_cache[team_abbrev] = result
            return result

        except Exception:
            return None

    def _get_team_zone_time(self, team_abbrev: str) -> Optional[Dict]:
        """Get team's offensive zone time percentage from NHL Edge API."""
        if not self._nhl_api or not team_abbrev:
            return None

        # Check cache
        if team_abbrev in self._zone_time_cache:
            return self._zone_time_cache[team_abbrev]

        try:
            zone_data = self._nhl_api.get_team_zone_time(team_abbrev)
            if zone_data:
                self._zone_time_cache[team_abbrev] = zone_data
            return zone_data
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

    def _estimate_game_total(self, team: str, opponent: str) -> float:
        """
        Estimate expected game total based on both teams' scoring.

        Higher game totals = more shots = more saves opportunities.
        """
        team_stats = self._get_team_sog_stats(team)
        opp_stats = self._get_team_sog_stats(opponent)

        team_gpg = team_stats.get('goals_per_game', 3.0) if team_stats else 3.0
        opp_gpg = opp_stats.get('goals_per_game', 3.0) if opp_stats else 3.0

        return team_gpg + opp_gpg

    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """Calculate goalie saves signal with INVERTED polarity."""

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

        # =====================================================================
        # COMPONENT 1: OPPONENT ZONE TIME (25% weight) - NEW
        # Higher OZ time = more offensive pressure = more shots = more saves
        # =====================================================================
        opponent_zone_data = self._get_team_zone_time(ctx.opponent) if ctx.opponent else None
        opponent_oz_pct = self.AVG_OZ_TIME_PCT

        zone_time_component = 0.0
        if opponent_zone_data:
            opponent_oz_pct = opponent_zone_data.get('all_offensive_pct', self.AVG_OZ_TIME_PCT)

            if opponent_oz_pct >= self.HIGH_OZ_TIME:
                zone_time_component = 0.5
                notes.append(f"High-pressure opponent ({opponent_oz_pct:.1f}% OZ time)")
            elif opponent_oz_pct <= self.LOW_OZ_TIME:
                zone_time_component = -0.5
                notes.append(f"Low-pressure opponent ({opponent_oz_pct:.1f}% OZ time)")
            else:
                # Linear scale between thresholds
                zone_time_component = (opponent_oz_pct - self.AVG_OZ_TIME_PCT) / (self.HIGH_OZ_TIME - self.AVG_OZ_TIME_PCT)
                zone_time_component = min(0.5, max(-0.5, zone_time_component))

        components.append(('opponent_zone_time', zone_time_component, 0.25))

        # =====================================================================
        # COMPONENT 2: GAME TOTAL CORRELATION (15% weight) - NEW
        # Higher expected game totals = more action = more saves
        # =====================================================================
        expected_total = self._estimate_game_total(ctx.team, ctx.opponent)
        total_diff = expected_total - self.AVG_GAME_TOTAL

        game_total_component = 0.0
        if total_diff > 1.0:
            game_total_component = 0.4
            notes.append(f"High-scoring matchup (exp {expected_total:.1f} total)")
        elif total_diff < -1.0:
            game_total_component = -0.4
            notes.append(f"Low-scoring matchup (exp {expected_total:.1f} total)")
        else:
            game_total_component = total_diff / 2.5  # Scale to -0.4 to +0.4
            game_total_component = min(0.4, max(-0.4, game_total_component))

        components.append(('game_total_correlation', game_total_component, 0.15))

        # =====================================================================
        # COMPONENT 3: OPPONENT SOG TENDENCY (30% weight)
        # Direct shot volume predictor
        # =====================================================================
        opponent_sog_data = self._get_team_sog_stats(ctx.opponent) if ctx.opponent else None
        opponent_sog = opponent_sog_data.get('sog_per_game', self.AVG_SOG_PER_GAME) if opponent_sog_data else self.AVG_SOG_PER_GAME

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

        components.append(('opponent_sog_tendency', workload_component, 0.30))

        # =====================================================================
        # COMPONENT 4: GOALIE FORM (15% weight)
        # Hot/cold goalie performance
        # =====================================================================
        goalie_form = self._get_goalie_form(player_id)
        save_pct = self.AVG_SAVE_PCT
        form_assessment = 'NEUTRAL'

        if goalie_form:
            save_pct = goalie_form.get('recent_save_pct', 0) or goalie_form.get('season_save_pct', self.AVG_SAVE_PCT)
            form_assessment = goalie_form.get('form_assessment', 'NEUTRAL')

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

        components.append(('goalie_form', form_component, 0.15))

        # =====================================================================
        # COMPONENT 5: EXPECTED SAVES VS LINE (15% weight)
        # Direct line comparison
        # =====================================================================
        expected_saves = opponent_sog * save_pct
        saves_diff = expected_saves - line
        saves_diff_pct = saves_diff / line if line > 0 else 0

        # Map to signal strength: +10% diff = +0.5 strength
        line_component = min(1.0, max(-1.0, saves_diff_pct * 5))
        components.append(('expected_vs_line', line_component, 0.15))

        if saves_diff > 2:
            notes.append(f"Expected {expected_saves:.1f} saves vs line {line}")
        elif saves_diff < -2:
            notes.append(f"Expected only {expected_saves:.1f} saves vs line {line}")

        # =====================================================================
        # CALCULATE WEIGHTED STRENGTH
        # =====================================================================
        if components:
            total_weight = sum(c[2] for c in components)
            raw_strength = sum(c[1] * c[2] for c in components) / total_weight if total_weight else 0
            raw_strength = max(-1.0, min(1.0, raw_strength))
        else:
            raw_strength = 0.0

        # =====================================================================
        # CRITICAL: INVERT THE SIGNAL POLARITY
        # Backtest showed 63.2% hit rate on NEGATIVE edge for saves
        # This means when model says OVER, UNDER actually wins more often
        # =====================================================================
        strength = -raw_strength  # INVERT the signal

        # Confidence based on data availability
        confidence = 0.75
        if not opponent_sog_data:
            confidence -= 0.10
        if not opponent_zone_data:
            confidence -= 0.10
        if not goalie_form or form_assessment == 'NEUTRAL':
            confidence -= 0.05

        # Build evidence (note the inversion in the explanation)
        raw_direction = "OVER" if raw_strength > 0.1 else "UNDER" if raw_strength < -0.1 else "neutral"
        final_direction = "UNDER" if strength > 0.1 else "OVER" if strength < -0.1 else "neutral"

        evidence = f"[CONTRARIAN] Raw signal: {raw_direction}, Final: {final_direction}. "
        evidence += f"Expected {expected_saves:.1f} saves (opp {opponent_sog:.1f} SOG × {save_pct:.3f} SV%)"
        if opponent_zone_data:
            evidence += f", OZ time {opponent_oz_pct:.1f}%"
        if notes:
            evidence += f" - {', '.join(notes[:2])}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,  # INVERTED strength
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'expected_saves': expected_saves,
                'prop_line': line,
                'opponent_sog': opponent_sog,
                'opponent_oz_pct': opponent_oz_pct,
                'expected_game_total': expected_total,
                'goalie_save_pct': save_pct,
                'form_assessment': form_assessment,
                'saves_diff': saves_diff,
                'raw_strength': raw_strength,
                'inverted_strength': strength,
                'components': {c[0]: c[1] for c in components},
            }
        )
