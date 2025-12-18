"""
Game Totals Signal

Evaluates game total (over/under) props using:
- Team offensive output (goals for per game)
- Team defensive quality (goals against per game)
- Goalie matchups (starting goalies' GAA, save %)
- Pace indicators (shots per game)

Created: December 18, 2025
Uses: NHL Official API team stats, goalie data
"""
from typing import Dict, Any, Optional
from .base import BaseSignal, SignalResult, PropContext

# Import NHL API and team normalization
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from providers.nhl_official_api import NHLOfficialAPI
    from nhl_sgp_engine.providers.nhl_data_provider import normalize_team
    HAS_NHL_API = True
except ImportError:
    HAS_NHL_API = False
    def normalize_team(t): return t  # Fallback


class GameTotalsSignal(BaseSignal):
    """
    Signal for game total (over/under) props.

    Methodology:
    1. Get both teams' goals per game (offense) from team stats
    2. Get both teams' goals against per game (defense) from goalie stats
    3. Factor in starting goalie matchups
    4. Calculate expected total and compare to line
    5. Adjust for pace (shots per game)

    Positive strength = OVER bias (expect more goals)
    Negative strength = UNDER bias (expect fewer goals)
    """

    # League averages for 2024-25 season
    AVG_GOALS_PER_TEAM = 3.0  # ~3 goals per team per game
    AVG_TOTAL = 6.0           # ~6 total goals per game
    AVG_GAA = 2.90            # League average GAA
    AVG_SAVE_PCT = 0.905

    # Thresholds for high/low scoring
    HIGH_SCORING_GPG = 3.5
    LOW_SCORING_GPG = 2.5
    ELITE_GAA = 2.50
    POOR_GAA = 3.30

    def __init__(self):
        """Initialize with NHL API if available."""
        self._nhl_api = NHLOfficialAPI() if HAS_NHL_API else None
        self._team_cache = {}

    @property
    def signal_type(self) -> str:
        return "game_totals"

    def _get_team_scoring_stats(self, team_name: str) -> Optional[Dict]:
        """Get team's scoring statistics."""
        if not self._nhl_api or not team_name:
            return None

        # Normalize team name to abbreviation (e.g., "Boston Bruins" -> "BOS")
        team_abbrev = normalize_team(team_name)

        # Check cache
        if team_abbrev in self._team_cache:
            return self._team_cache[team_abbrev]

        try:
            stats = self._nhl_api.get_team_stats(team_abbrev)
            skaters = stats.get('skaters', [])
            goalies = stats.get('goalies', [])

            if not skaters:
                return None

            # Calculate team totals from skaters
            total_goals = sum(s.get('goals', 0) for s in skaters)
            total_shots = sum(s.get('shots', 0) for s in skaters)
            max_games = max(s.get('games_played', 0) for s in skaters) if skaters else 0

            if max_games == 0:
                return None

            # Get primary goalie stats (most games started)
            primary_goalie = None
            if goalies:
                primary_goalie = max(goalies, key=lambda g: g.get('games_started', 0))

            result = {
                'team': team_abbrev,
                'goals_for': total_goals,
                'shots_for': total_shots,
                'games_played': max_games,
                'goals_per_game': total_goals / max_games,
                'shots_per_game': total_shots / max_games,
                'primary_goalie': primary_goalie.get('name') if primary_goalie else None,
                'goalie_gaa': primary_goalie.get('gaa', self.AVG_GAA) if primary_goalie else self.AVG_GAA,
                'goalie_save_pct': primary_goalie.get('save_pct', self.AVG_SAVE_PCT) if primary_goalie else self.AVG_SAVE_PCT,
                'goals_against': primary_goalie.get('goals_against', 0) if primary_goalie else 0,
                'goalie_games': primary_goalie.get('games_played', 0) if primary_goalie else 0,
            }

            # Calculate goals against per game
            if result['goalie_games'] > 0 and result['goals_against'] > 0:
                result['goals_against_per_game'] = result['goals_against'] / result['goalie_games']
            else:
                result['goals_against_per_game'] = self.AVG_GOALS_PER_TEAM

            self._team_cache[team_abbrev] = result
            return result

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
        """Calculate game totals signal."""

        ctx = game_context if isinstance(game_context, PropContext) else PropContext(**game_context)

        # Only relevant for totals props
        if stat_type != 'totals' and stat_type != 'total':
            return SignalResult(
                signal_type=self.signal_type,
                strength=0.0,
                confidence=0.3,
                evidence=f"Game totals signal not relevant for {stat_type}",
                raw_data={'reason': 'irrelevant_stat'}
            )

        notes = []
        components = []

        # Get both teams' stats
        home_team = ctx.team if ctx.is_home else ctx.opponent
        away_team = ctx.opponent if ctx.is_home else ctx.team

        home_stats = self._get_team_scoring_stats(home_team) if home_team else None
        away_stats = self._get_team_scoring_stats(away_team) if away_team else None

        # Calculate expected total
        home_gpg = home_stats.get('goals_per_game', self.AVG_GOALS_PER_TEAM) if home_stats else self.AVG_GOALS_PER_TEAM
        away_gpg = away_stats.get('goals_per_game', self.AVG_GOALS_PER_TEAM) if away_stats else self.AVG_GOALS_PER_TEAM

        home_gaa = home_stats.get('goals_against_per_game', self.AVG_GOALS_PER_TEAM) if home_stats else self.AVG_GOALS_PER_TEAM
        away_gaa = away_stats.get('goals_against_per_game', self.AVG_GOALS_PER_TEAM) if away_stats else self.AVG_GOALS_PER_TEAM

        # Expected total: average of offensive outputs adjusted by opponent defense
        # Home team expected goals = (home_gpg + away_gaa) / 2
        # Away team expected goals = (away_gpg + home_gaa) / 2
        home_expected = (home_gpg + away_gaa) / 2
        away_expected = (away_gpg + home_gaa) / 2
        expected_total = home_expected + away_expected

        # Component 1: Expected vs line (50% weight)
        total_diff = expected_total - line
        total_diff_pct = total_diff / line if line > 0 else 0

        # Map to signal strength: +10% diff = +0.5 strength
        line_component = min(1.0, max(-1.0, total_diff_pct * 5))
        components.append(('expected_vs_line', line_component, 0.50))

        if total_diff > 0.5:
            notes.append(f"Expected {expected_total:.1f} vs line {line}")
        elif total_diff < -0.5:
            notes.append(f"Expected only {expected_total:.1f} vs line {line}")

        # Component 2: Offensive firepower (25% weight)
        combined_offense = (home_gpg + away_gpg) / 2
        offense_component = 0.0
        if combined_offense >= self.HIGH_SCORING_GPG:
            offense_component = 0.5
            notes.append(f"High-scoring matchup ({combined_offense:.2f} GPG avg)")
        elif combined_offense <= self.LOW_SCORING_GPG:
            offense_component = -0.5
            notes.append(f"Low-scoring matchup ({combined_offense:.2f} GPG avg)")
        else:
            # Linear scale
            offense_component = (combined_offense - self.AVG_GOALS_PER_TEAM) / (self.HIGH_SCORING_GPG - self.AVG_GOALS_PER_TEAM)
            offense_component = min(0.5, max(-0.5, offense_component))
        components.append(('offensive_firepower', offense_component, 0.25))

        # Component 3: Goalie quality (25% weight)
        home_goalie_gaa = home_stats.get('goalie_gaa', self.AVG_GAA) if home_stats else self.AVG_GAA
        away_goalie_gaa = away_stats.get('goalie_gaa', self.AVG_GAA) if away_stats else self.AVG_GAA
        combined_gaa = (home_goalie_gaa + away_goalie_gaa) / 2

        goalie_component = 0.0
        if combined_gaa >= self.POOR_GAA:
            goalie_component = 0.4  # Poor goalies = more goals
            notes.append(f"Weak goaltending ({combined_gaa:.2f} combined GAA)")
        elif combined_gaa <= self.ELITE_GAA:
            goalie_component = -0.4  # Elite goalies = fewer goals
            notes.append(f"Strong goaltending ({combined_gaa:.2f} combined GAA)")
        else:
            # Linear scale
            goalie_component = (combined_gaa - self.AVG_GAA) / (self.POOR_GAA - self.AVG_GAA)
            goalie_component = min(0.4, max(-0.4, goalie_component))
        components.append(('goalie_quality', goalie_component, 0.25))

        # Calculate weighted strength
        if components:
            total_weight = sum(c[2] for c in components)
            strength = sum(c[1] * c[2] for c in components) / total_weight if total_weight else 0
            strength = max(-1.0, min(1.0, strength))
        else:
            strength = 0.0

        # Confidence based on data availability
        confidence = 0.75
        if not home_stats:
            confidence -= 0.15
        if not away_stats:
            confidence -= 0.15

        # Build evidence
        direction = "OVER" if strength > 0.1 else "UNDER" if strength < -0.1 else "neutral"
        evidence = f"Expected {expected_total:.1f} total ({home_team} {home_expected:.1f} + {away_team} {away_expected:.1f})"
        if notes:
            evidence += f" - {', '.join(notes[:2])}"

        return SignalResult(
            signal_type=self.signal_type,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'expected_total': expected_total,
                'prop_line': line,
                'home_team': home_team,
                'away_team': away_team,
                'home_gpg': home_gpg,
                'away_gpg': away_gpg,
                'home_gaa': home_gaa,
                'away_gaa': away_gaa,
                'home_expected': home_expected,
                'away_expected': away_expected,
                'combined_offense': combined_offense,
                'combined_gaa': combined_gaa,
                'total_diff': total_diff,
                'components': {c[0]: c[1] for c in components},
            }
        )
