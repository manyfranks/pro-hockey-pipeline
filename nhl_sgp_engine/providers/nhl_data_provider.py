"""
NHL Data Provider for SGP Engine

Implements the SportDataProvider interface from MULTI_LEAGUE_ARCHITECTURE.md.
This is the PRIMARY data source for the SGP engine - queries NHL API directly.

The points pipeline is SUPPLEMENTAL - provides is_scoreable, rank, line deployment
as bonus context, but the SGP engine can function without it.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional, Any

from providers.nhl_official_api import NHLOfficialAPI


# ============================================================================
# Team Name to Abbreviation Mapping
# ============================================================================

NHL_TEAM_ABBREVS = {
    # Full names from Odds API -> NHL API abbreviations
    'Anaheim Ducks': 'ANA',
    'Arizona Coyotes': 'ARI',
    'Boston Bruins': 'BOS',
    'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY',
    'Carolina Hurricanes': 'CAR',
    'Chicago Blackhawks': 'CHI',
    'Colorado Avalanche': 'COL',
    'Columbus Blue Jackets': 'CBJ',
    'Dallas Stars': 'DAL',
    'Detroit Red Wings': 'DET',
    'Edmonton Oilers': 'EDM',
    'Florida Panthers': 'FLA',
    'Los Angeles Kings': 'LAK',
    'Minnesota Wild': 'MIN',
    'Montreal Canadiens': 'MTL',
    'Montréal Canadiens': 'MTL',  # With accent
    'Nashville Predators': 'NSH',
    'New Jersey Devils': 'NJD',
    'New York Islanders': 'NYI',
    'New York Rangers': 'NYR',
    'Ottawa Senators': 'OTT',
    'Philadelphia Flyers': 'PHI',
    'Pittsburgh Penguins': 'PIT',
    'San Jose Sharks': 'SJS',
    'Seattle Kraken': 'SEA',
    'St. Louis Blues': 'STL',
    'St Louis Blues': 'STL',
    'Tampa Bay Lightning': 'TBL',
    'Toronto Maple Leafs': 'TOR',
    'Utah Hockey Club': 'UTA',
    'Utah Mammoth': 'UTA',  # Alternative name
    'Vancouver Canucks': 'VAN',
    'Vegas Golden Knights': 'VGK',
    'Washington Capitals': 'WSH',
    'Winnipeg Jets': 'WPG',
}

# Reverse mapping
ABBREV_TO_TEAM = {v: k for k, v in NHL_TEAM_ABBREVS.items()}


def normalize_team(team: str) -> str:
    """
    Convert team name to NHL API abbreviation.

    Handles:
    - Full names (e.g., "Winnipeg Jets" -> "WPG")
    - Already abbreviated (e.g., "WPG" -> "WPG")
    - Mixed case (e.g., "winnipeg jets" -> "WPG")
    """
    if not team:
        return ''

    # Already an abbreviation?
    if team.upper() in ABBREV_TO_TEAM:
        return team.upper()

    # Try full name mapping
    if team in NHL_TEAM_ABBREVS:
        return NHL_TEAM_ABBREVS[team]

    # Try case-insensitive matching
    team_lower = team.lower()
    for full_name, abbrev in NHL_TEAM_ABBREVS.items():
        if full_name.lower() == team_lower:
            return abbrev

    # Try partial match (e.g., "Rangers" -> "NYR")
    for full_name, abbrev in NHL_TEAM_ABBREVS.items():
        if team_lower in full_name.lower():
            return abbrev

    # Return as-is if no match
    return team


# ============================================================================
# Abstract Interface (from MULTI_LEAGUE_ARCHITECTURE.md Section 5)
# ============================================================================

class SportDataProvider(ABC):
    """Abstract interface for sport-specific data providers."""

    @property
    @abstractmethod
    def league(self) -> str:
        """Return league identifier ('NFL', 'NBA', 'MLB', 'NHL')."""
        pass

    @abstractmethod
    def get_player_stats(
        self,
        player_id: str,
        season: int,
        last_n_games: Optional[int] = None
    ) -> List[Dict]:
        """Get player game logs."""
        pass

    @abstractmethod
    def get_team_defense(self, team: str, season: int) -> Dict:
        """Get team defensive statistics."""
        pass

    @abstractmethod
    def get_schedule(self, season: int, game_date: Optional[date] = None) -> List[Dict]:
        """Get games for a date or full schedule."""
        pass

    @abstractmethod
    def get_prop_types(self) -> List[str]:
        """Return supported prop types for this sport."""
        pass


# ============================================================================
# NHL Implementation
# ============================================================================

class NHLDataProvider(SportDataProvider):
    """
    NHL Data Provider using the official NHL API.

    This is the PRIMARY data source for the NHL SGP engine.
    Provides all data needed for the 5-signal framework:
    - Trend: Player game logs and recent form
    - Usage: TOI, games played
    - Matchup: Goalie stats, team defense
    - Environment: Home/away, schedule
    - Correlation: Game context

    The points pipeline (nhl_daily_predictions) is SUPPLEMENTAL - adds
    is_scoreable, rank, line deployment as bonus context.
    """

    def __init__(self):
        self.api = NHLOfficialAPI()
        self._player_cache: Dict[int, Dict] = {}
        self._team_cache: Dict[str, Dict] = {}

    @property
    def league(self) -> str:
        return 'NHL'

    def get_prop_types(self) -> List[str]:
        """Return ALL supported NHL prop types."""
        return [
            'points',           # Goals + Assists
            'goals',            # Goals scored
            'assists',          # Assists
            'shots_on_goal',    # SOG
            'blocked_shots',    # Blocked shots
            'saves',            # Goalie saves
            'goals_against',    # Goalie goals against
        ]

    # =========================================================================
    # PLAYER DATA (for Trend & Line Value signals)
    # =========================================================================

    def get_player_stats(
        self,
        player_id: str,
        season: int = None,
        last_n_games: Optional[int] = None
    ) -> List[Dict]:
        """
        Get player game logs.

        Args:
            player_id: NHL player ID (as string for interface compatibility)
            season: Season year (not used - API returns current)
            last_n_games: Number of recent games

        Returns:
            List of game log entries
        """
        pid = int(player_id)
        num_games = last_n_games or 10

        return self.api.get_player_game_log(pid, num_games)

    def get_player_season_stats(self, player_id: int) -> Optional[Dict]:
        """
        Get player's season statistics.

        Returns dict with:
        - season_games, season_goals, season_assists, season_points
        - season_shots, season_pp_goals, season_pp_points
        - avg_toi_minutes
        """
        if player_id in self._player_cache:
            return self._player_cache[player_id]

        info = self.api.get_player_info(player_id)
        if info:
            self._player_cache[player_id] = info

        return info

    def get_player_recent_form(self, player_id: int, num_games: int = 10) -> Dict:
        """
        Get player's recent form metrics.

        Returns dict with:
        - recent_games, recent_goals, recent_assists, recent_points
        - recent_ppg, point_streak
        """
        return self.api.calculate_recent_form(player_id, num_games)

    def get_player_by_name(self, player_name: str, team: str = None) -> Optional[Dict]:
        """
        Find player by name (fuzzy match).

        Args:
            player_name: Player's full name
            team: Optional team (full name or abbreviation)

        Returns:
            Player info dict or None
        """
        # Normalize name for matching
        search_name = player_name.lower().strip()

        # If team provided, search that team's roster
        if team:
            team_abbrev = normalize_team(team)
            team_stats = self.api.get_team_stats(team_abbrev)
            for skater in team_stats.get('skaters', []):
                if search_name in skater['name'].lower():
                    return self.get_player_season_stats(skater['player_id'])

            for goalie in team_stats.get('goalies', []):
                if search_name in goalie['name'].lower():
                    return self.get_player_season_stats(goalie['player_id'])

        # If no team, we'd need to search all teams (expensive)
        # For now, return None and require team context
        return None

    # =========================================================================
    # TEAM DATA (for Matchup signal)
    # =========================================================================

    def get_team_defense(self, team: str, season: int = None) -> Dict:
        """
        Get team defensive statistics.

        Returns:
        - goals_against_per_game
        - shots_against_per_game
        - save_percentage
        - pk_percentage
        """
        team_abbrev = normalize_team(team)

        if team_abbrev in self._team_cache:
            return self._team_cache[team_abbrev]

        team_stats = self.api.get_team_stats(team_abbrev)
        goalies = team_stats.get('goalies', [])

        # Calculate team defensive metrics from goalie stats
        total_ga = sum(g.get('goals_against', 0) for g in goalies)
        total_sa = sum(g.get('shots_against', 0) for g in goalies)
        total_games = sum(g.get('games_played', 0) for g in goalies) // 2  # Rough estimate

        # Get primary goalie
        primary_goalie = max(goalies, key=lambda g: g.get('games_started', 0)) if goalies else None

        defense = {
            'team': team_abbrev,
            'goals_against': total_ga,
            'shots_against': total_sa,
            'games': total_games,
            'goals_against_per_game': total_ga / total_games if total_games > 0 else 3.0,
            'shots_against_per_game': total_sa / total_games if total_games > 0 else 30.0,
            'save_percentage': primary_goalie.get('save_pct', 0.900) if primary_goalie else 0.900,
            'primary_goalie_id': primary_goalie.get('player_id') if primary_goalie else None,
            'primary_goalie_name': primary_goalie.get('name') if primary_goalie else None,
            'primary_goalie_gaa': primary_goalie.get('gaa', 3.0) if primary_goalie else 3.0,
        }

        self._team_cache[team_abbrev] = defense
        return defense

    def get_goalie_stats(self, goalie_id: int) -> Optional[Dict]:
        """Get detailed stats for a specific goalie."""
        return self.api.get_goalie_stats(goalie_id)

    def get_opposing_goalie(self, opponent_team: str) -> Optional[Dict]:
        """Get the probable starting goalie for opponent."""
        team_abbrev = normalize_team(opponent_team)
        return self.api.get_probable_goalie(team_abbrev)

    # =========================================================================
    # SCHEDULE (for Environment signal)
    # =========================================================================

    def get_schedule(self, season: int = None, game_date: Optional[date] = None) -> List[Dict]:
        """
        Get games for a date.

        Args:
            season: Season year (not used)
            game_date: Date to get games for

        Returns:
            List of game dictionaries
        """
        game_date = game_date or date.today()
        return self.api.get_games_by_date(game_date)

    def get_team_schedule(self, team: str, num_days: int = 7) -> List[Dict]:
        """
        Get upcoming schedule for a team.

        Used to detect back-to-backs, rest days.
        """
        from datetime import timedelta

        team_abbrev = normalize_team(team)

        games = []
        for i in range(num_days):
            check_date = date.today() + timedelta(days=i)
            day_games = self.api.get_games_by_date(check_date)
            for game in day_games:
                if game['home_team'] == team_abbrev or game['away_team'] == team_abbrev:
                    game['is_home'] = game['home_team'] == team_abbrev
                    games.append(game)

        return games

    # =========================================================================
    # GAME DATA (for Settlement)
    # =========================================================================

    def get_box_score(self, game_id: int) -> Optional[Dict]:
        """Get box score for a completed game."""
        return self.api.get_box_score(game_id)

    def get_player_game_stats(
        self,
        player_name: str,
        game_date: date,
        stat_type: str
    ) -> Optional[float]:
        """
        Get a player's stat from a specific game.

        Used for settlement.
        """
        # Get games for date
        games = self.api.get_games_by_date(game_date)

        for game in games:
            if game['game_state'] not in ['OFF', 'FINAL']:
                continue

            box = self.api.get_box_score(game['game_id'])
            if not box:
                continue

            for player in box.get('players', []):
                if player_name.lower() in player.get('name', '').lower():
                    # Return the requested stat
                    stat_map = {
                        'points': player.get('points', 0),
                        'goals': player.get('goals', 0),
                        'assists': player.get('assists', 0),
                        'shots_on_goal': player.get('shots', 0),
                        'blocked_shots': 0,  # Not in standard box score
                        'saves': int(player.get('saves', 0)) if player.get('saves') else 0,
                    }
                    return stat_map.get(stat_type)

        return None

    # =========================================================================
    # PROP-SPECIFIC DATA
    # =========================================================================

    def get_player_stat_context(
        self,
        player_name: str,
        stat_type: str,
        team: str = None,
    ) -> Optional[Dict]:
        """
        Get all context needed to evaluate a prop.

        This is the main method the SGP engine should call.

        Args:
            player_name: Player's full name
            stat_type: points, goals, assists, shots_on_goal, etc.
            team: Team abbreviation (optional but helps matching)

        Returns:
            Dict with:
            - player_id, name, team, position
            - season_avg (for the stat)
            - recent_avg (L10 for the stat)
            - games_played
            - trend_direction (+1, 0, -1)
            - raw_season_stats
            - raw_recent_stats
        """
        # Find player
        player_info = self.get_player_by_name(player_name, team)
        if not player_info:
            return None

        player_id = player_info['player_id']

        # Get recent form
        recent = self.get_player_recent_form(player_id, 10)

        # Calculate stat-specific averages
        season_games = player_info.get('season_games', 0)
        recent_games = recent.get('recent_games', 0)

        # Stat mapping
        stat_season_map = {
            'points': player_info.get('season_points', 0),
            'goals': player_info.get('season_goals', 0),
            'assists': player_info.get('season_assists', 0),
            'shots_on_goal': player_info.get('season_shots', 0),
        }

        stat_recent_map = {
            'points': recent.get('recent_points', 0),
            'goals': recent.get('recent_goals', 0),
            'assists': recent.get('recent_assists', 0),
            'shots_on_goal': sum(
                log.get('shots', 0) for log in self.api.get_player_game_log(player_id, 10)
            ),
        }

        season_total = stat_season_map.get(stat_type, 0)
        recent_total = stat_recent_map.get(stat_type, 0)

        season_avg = season_total / season_games if season_games > 0 else 0
        recent_avg = recent_total / recent_games if recent_games > 0 else 0

        # Calculate trend
        if season_avg > 0:
            trend_pct = (recent_avg - season_avg) / season_avg
            if trend_pct > 0.15:
                trend_direction = 1  # Hot
            elif trend_pct < -0.15:
                trend_direction = -1  # Cold
            else:
                trend_direction = 0  # Stable
        else:
            trend_direction = 0

        return {
            'player_id': player_id,
            'player_name': player_info['name'],
            'team': player_info.get('team'),
            'position': player_info.get('position'),
            'stat_type': stat_type,
            'season_games': season_games,
            'season_avg': round(season_avg, 3),
            'season_total': season_total,
            'recent_games': recent_games,
            'recent_avg': round(recent_avg, 3),
            'recent_total': recent_total,
            'trend_direction': trend_direction,
            'trend_pct': round((recent_avg - season_avg) / season_avg * 100, 1) if season_avg > 0 else 0,
            'point_streak': recent.get('point_streak', 0),
            'avg_toi_minutes': player_info.get('season_toi_per_game', 0),
            'raw_season_stats': player_info,
            'raw_recent_stats': recent,
        }

    def get_matchup_context(
        self,
        team: str,
        opponent: str,
        is_home: bool,
    ) -> Dict:
        """
        Get matchup context for a game.

        Returns:
        - opposing_goalie info
        - opponent defense ranking
        - home/away factors
        """
        team_abbrev = normalize_team(team)
        opp_abbrev = normalize_team(opponent)

        opp_defense = self.get_team_defense(opp_abbrev)
        opp_goalie = self.get_opposing_goalie(opp_abbrev)

        return {
            'team': team_abbrev,
            'opponent': opp_abbrev,
            'is_home': is_home,
            'opposing_goalie_id': opp_goalie.get('player_id') if opp_goalie else None,
            'opposing_goalie_name': opp_goalie.get('name') if opp_goalie else None,
            'opposing_goalie_sv_pct': opp_goalie.get('save_pct', 0.900) if opp_goalie else 0.900,
            'opposing_goalie_gaa': opp_goalie.get('gaa', 3.0) if opp_goalie else 3.0,
            'goalie_confirmed': opp_goalie.get('is_confirmed', False) if opp_goalie else False,
            'opponent_ga_per_game': opp_defense.get('goals_against_per_game', 3.0),
            'opponent_sa_per_game': opp_defense.get('shots_against_per_game', 30.0),
        }


# ============================================================================
# Test
# ============================================================================

if __name__ == '__main__':
    provider = NHLDataProvider()

    print("=" * 70)
    print("NHL DATA PROVIDER TEST")
    print("=" * 70)

    # Test 1: Prop types
    print(f"\nSupported prop types: {provider.get_prop_types()}")

    # Test 2: Player context
    print("\n--- Player Context: Connor McDavid ---")
    ctx = provider.get_player_stat_context('Connor McDavid', 'points', 'EDM')
    if ctx:
        print(f"  Season avg: {ctx['season_avg']} PPG")
        print(f"  Recent avg: {ctx['recent_avg']} PPG (L{ctx['recent_games']})")
        print(f"  Trend: {ctx['trend_pct']:+.1f}% ({['Cold', 'Stable', 'Hot'][ctx['trend_direction']+1]})")
        print(f"  Point streak: {ctx['point_streak']} games")

    # Test 3: Matchup context
    print("\n--- Matchup Context: EDM vs TOR ---")
    matchup = provider.get_matchup_context('EDM', 'TOR', is_home=False)
    print(f"  Opposing goalie: {matchup['opposing_goalie_name']}")
    print(f"  Goalie SV%: {matchup['opposing_goalie_sv_pct']:.3f}")
    print(f"  Goalie GAA: {matchup['opposing_goalie_gaa']:.2f}")
    print(f"  Opp GA/game: {matchup['opponent_ga_per_game']:.2f}")

    # Test 4: Today's games
    print("\n--- Today's Schedule ---")
    games = provider.get_schedule()
    print(f"  {len(games)} games scheduled")
    for g in games[:3]:
        print(f"    {g['away_team']} @ {g['home_team']}")
