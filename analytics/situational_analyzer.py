# nhl_isolated/analytics/situational_analyzer.py
"""
Situational Analyzer for NHL Player Points Algorithm

Handles fatigue and context-based adjustments:
- Back-to-back (B2B) game detection
- B2B2B (3 games in 3 nights) detection
- Road trip fatigue
- Home/away modifiers

References NHL_ALGORITHM_ADR.md Section 4 (Fatigue & Edge Cases)
"""
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple


# Fatigue penalty constants (from ADR)
B2B_SKATER_PENALTY = -0.08      # -8% for back-to-back
B2B2B_SKATER_PENALTY = -0.15    # -15% for 3 games in 3 nights
B2B_GOALIE_BOOST = 0.10         # +10% when opposing goalie is on B2B (tired = weaker)
WELL_RESTED_GOALIE_PENALTY = -0.05  # -5% when opposing goalie has 2+ days rest

# Road trip fatigue
ROAD_TRIP_4_PENALTY = -0.05     # 4+ consecutive away games
ROAD_TRIP_6_PENALTY = -0.10     # 6+ consecutive away games

# Home ice advantage
HOME_BONUS = 0.03               # ~3% boost for home team


class ScheduleAnalyzer:
    """
    Analyzes team schedules to detect fatigue situations.

    Caches schedule data to avoid repeated API calls.
    """

    def __init__(self, provider=None):
        """
        Initialize with optional data provider.

        Args:
            provider: CachedNHLProvider instance for fetching schedule data
        """
        self.provider = provider
        self._schedule_cache: Dict[str, List[Dict]] = {}  # team -> list of games
        self._loaded_date_range: Optional[Tuple[date, date]] = None

    def load_schedule_range(self, start_date: date, end_date: date) -> None:
        """
        Load schedule data for a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
        """
        if self.provider is None:
            return

        self._schedule_cache.clear()

        current = start_date
        while current <= end_date:
            try:
                games = self.provider.get_games_by_date(current)
                for game in games:
                    home_team = game.get('HomeTeam')
                    away_team = game.get('AwayTeam')
                    game_date = current

                    game_record = {
                        'date': game_date,
                        'game_id': game.get('GameID'),
                        'home_team': home_team,
                        'away_team': away_team,
                        'is_home': None,  # Set per-team below
                    }

                    # Add to home team's schedule
                    if home_team:
                        if home_team not in self._schedule_cache:
                            self._schedule_cache[home_team] = []
                        home_record = {**game_record, 'is_home': True}
                        self._schedule_cache[home_team].append(home_record)

                    # Add to away team's schedule
                    if away_team:
                        if away_team not in self._schedule_cache:
                            self._schedule_cache[away_team] = []
                        away_record = {**game_record, 'is_home': False}
                        self._schedule_cache[away_team].append(away_record)

            except Exception as e:
                print(f"[Schedule] Error loading {current}: {e}")

            current += timedelta(days=1)

        self._loaded_date_range = (start_date, end_date)

        # Sort each team's schedule by date
        for team in self._schedule_cache:
            self._schedule_cache[team].sort(key=lambda x: x['date'])

    def get_team_games_in_range(self, team: str, start_date: date, end_date: date) -> List[Dict]:
        """Get all games for a team within a date range."""
        if team not in self._schedule_cache:
            return []

        return [
            g for g in self._schedule_cache[team]
            if start_date <= g['date'] <= end_date
        ]

    def is_back_to_back(self, team: str, game_date: date) -> bool:
        """
        Check if a team is playing on a back-to-back.

        B2B = team played yesterday.

        Args:
            team: Team abbreviation
            game_date: Date of the game to check

        Returns:
            True if team played yesterday
        """
        yesterday = game_date - timedelta(days=1)
        games_yesterday = self.get_team_games_in_range(team, yesterday, yesterday)
        return len(games_yesterday) > 0

    def is_back_to_back_to_back(self, team: str, game_date: date) -> bool:
        """
        Check if a team is playing their 3rd game in 3 nights.

        B2B2B = team played both yesterday AND 2 days ago.

        Args:
            team: Team abbreviation
            game_date: Date of the game to check

        Returns:
            True if team played both of the last 2 days
        """
        yesterday = game_date - timedelta(days=1)
        two_days_ago = game_date - timedelta(days=2)

        games = self.get_team_games_in_range(team, two_days_ago, yesterday)

        # Need games on BOTH days for B2B2B
        dates_played = set(g['date'] for g in games)
        return yesterday in dates_played and two_days_ago in dates_played

    def get_days_rest(self, team: str, game_date: date) -> int:
        """
        Get number of days since team's last game.

        Args:
            team: Team abbreviation
            game_date: Date of the game to check

        Returns:
            Days since last game (0 = B2B, 1 = normal, 2+ = well rested)
        """
        if team not in self._schedule_cache:
            return 1  # Default to normal rest

        team_games = self._schedule_cache[team]

        # Find most recent game before game_date
        previous_games = [g for g in team_games if g['date'] < game_date]

        if not previous_games:
            return 7  # No previous game found, assume well rested

        last_game = max(previous_games, key=lambda x: x['date'])
        days_since = (game_date - last_game['date']).days

        return days_since

    def get_consecutive_away_games(self, team: str, game_date: date) -> int:
        """
        Count consecutive away games including and before game_date.

        Args:
            team: Team abbreviation
            game_date: Date of the game to check

        Returns:
            Number of consecutive away games (0 if home game)
        """
        if team not in self._schedule_cache:
            return 0

        team_games = sorted(self._schedule_cache[team], key=lambda x: x['date'])

        # Find games up to and including game_date
        games_to_check = [g for g in team_games if g['date'] <= game_date]

        if not games_to_check:
            return 0

        # Count backwards from game_date
        consecutive_away = 0
        for game in reversed(games_to_check):
            if game['is_home']:
                break
            consecutive_away += 1

        return consecutive_away


def calculate_situational_score(
    player_data: Dict[str, Any],
    schedule_analyzer: Optional[ScheduleAnalyzer] = None,
    game_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate the situational score for a player.

    Factors:
    - Home/away status
    - Back-to-back fatigue (skater penalty)
    - Opposing goalie fatigue (boost if goalie on B2B)
    - Road trip fatigue

    Args:
        player_data: Enriched player dictionary
        schedule_analyzer: ScheduleAnalyzer instance with loaded schedule
        game_date: Date of the game

    Returns:
        Dictionary with:
        - situational_score: Score modifier (0-1 scale, 0.5 = neutral)
        - situational_details: Breakdown of factors
    """
    team = player_data.get('team')
    opponent = player_data.get('opponent')
    is_home = player_data.get('is_home', False)

    # Base score (neutral)
    base_score = 0.5

    # Track adjustments
    adjustments = []

    # Home ice advantage
    home_adjustment = HOME_BONUS if is_home else 0.0
    if home_adjustment:
        adjustments.append(('home_ice', home_adjustment))

    # B2B detection (requires schedule analyzer)
    is_b2b = False
    is_b2b2b = False
    skater_fatigue_penalty = 0.0
    days_rest = 1
    consecutive_away = 0
    road_trip_penalty = 0.0

    # Opposing goalie fatigue
    opposing_goalie_b2b = False
    opposing_goalie_days_rest = 1
    goalie_fatigue_boost = 0.0

    if schedule_analyzer and team and game_date:
        # Check skater's team fatigue
        is_b2b = schedule_analyzer.is_back_to_back(team, game_date)
        is_b2b2b = schedule_analyzer.is_back_to_back_to_back(team, game_date)
        days_rest = schedule_analyzer.get_days_rest(team, game_date)

        if is_b2b2b:
            skater_fatigue_penalty = B2B2B_SKATER_PENALTY
            adjustments.append(('b2b2b_fatigue', skater_fatigue_penalty))
        elif is_b2b:
            skater_fatigue_penalty = B2B_SKATER_PENALTY
            adjustments.append(('b2b_fatigue', skater_fatigue_penalty))

        # Road trip fatigue
        consecutive_away = schedule_analyzer.get_consecutive_away_games(team, game_date)
        if consecutive_away >= 6:
            road_trip_penalty = ROAD_TRIP_6_PENALTY
            adjustments.append(('road_trip_6+', road_trip_penalty))
        elif consecutive_away >= 4:
            road_trip_penalty = ROAD_TRIP_4_PENALTY
            adjustments.append(('road_trip_4+', road_trip_penalty))

        # Check opposing team's fatigue (affects their goalie)
        if opponent:
            opposing_goalie_b2b = schedule_analyzer.is_back_to_back(opponent, game_date)
            opposing_goalie_days_rest = schedule_analyzer.get_days_rest(opponent, game_date)

            if opposing_goalie_b2b:
                goalie_fatigue_boost = B2B_GOALIE_BOOST
                adjustments.append(('opposing_goalie_b2b', goalie_fatigue_boost))
            elif opposing_goalie_days_rest >= 3:
                # Well-rested goalie is slightly harder to score on
                goalie_fatigue_boost = WELL_RESTED_GOALIE_PENALTY
                adjustments.append(('opposing_goalie_rested', goalie_fatigue_boost))

    # Calculate total adjustment
    total_adjustment = sum(adj[1] for adj in adjustments)

    # Final situational score (clamped to 0-1)
    situational_score = max(0.0, min(1.0, base_score + total_adjustment))

    return {
        'situational_score': round(situational_score, 4),
        'situational_details': {
            'is_home': is_home,
            'home_adjustment': round(home_adjustment, 4),
            'is_b2b': is_b2b,
            'is_b2b2b': is_b2b2b,
            'days_rest': days_rest,
            'skater_fatigue_penalty': round(skater_fatigue_penalty, 4),
            'consecutive_away_games': consecutive_away,
            'road_trip_penalty': round(road_trip_penalty, 4),
            'opposing_goalie_b2b': opposing_goalie_b2b,
            'opposing_goalie_days_rest': opposing_goalie_days_rest,
            'goalie_fatigue_boost': round(goalie_fatigue_boost, 4),
            'total_adjustment': round(total_adjustment, 4),
            'adjustments': adjustments,
        }
    }


def calculate_situational_batch(
    players: List[Dict[str, Any]],
    schedule_analyzer: Optional[ScheduleAnalyzer] = None,
    game_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """
    Calculate situational scores for a batch of players.

    Args:
        players: List of enriched player dictionaries
        schedule_analyzer: ScheduleAnalyzer instance
        game_date: Date of the games

    Returns:
        Players with situational scores added
    """
    for player in players:
        result = calculate_situational_score(player, schedule_analyzer, game_date)
        player['situational_score'] = result['situational_score']
        player['situational_details'] = result['situational_details']

    return players


if __name__ == '__main__':
    # Test with sample data
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env.local'))

    from providers.cached_provider import CachedNHLProvider

    print("=" * 70)
    print("SITUATIONAL ANALYZER TEST")
    print("=" * 70)

    # Initialize provider and analyzer
    provider = CachedNHLProvider()
    analyzer = ScheduleAnalyzer(provider)

    # Load 10-day schedule window
    test_date = date(2025, 11, 29)  # Known to have B2B games
    start_date = test_date - timedelta(days=7)
    end_date = test_date + timedelta(days=3)

    print(f"\nLoading schedule from {start_date} to {end_date}...")
    analyzer.load_schedule_range(start_date, end_date)

    # Find teams with B2B on test_date
    print(f"\n--- B2B Analysis for {test_date} ---")

    b2b_teams = []
    for team in analyzer._schedule_cache.keys():
        if analyzer.is_back_to_back(team, test_date):
            is_b2b2b = analyzer.is_back_to_back_to_back(team, test_date)
            b2b_teams.append((team, is_b2b2b))

    print(f"Teams on B2B: {len(b2b_teams)}")
    for team, is_b2b2b in b2b_teams:
        status = "B2B2B" if is_b2b2b else "B2B"
        print(f"  {team}: {status}")

    # Test situational calculation
    if b2b_teams:
        test_team = b2b_teams[0][0]
        sample_player = {
            'player_name': 'Test Player',
            'team': test_team,
            'opponent': 'OPP',
            'is_home': False,
        }

        result = calculate_situational_score(sample_player, analyzer, test_date)

        print(f"\n--- Sample Situational Score ({test_team} player) ---")
        print(f"Score: {result['situational_score']}")
        print(f"Details:")
        for k, v in result['situational_details'].items():
            if k != 'adjustments':
                print(f"  {k}: {v}")
        print(f"  Adjustments applied: {result['situational_details']['adjustments']}")
