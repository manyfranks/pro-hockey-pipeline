# nhl_isolated/pipeline/enrichment.py
"""
NHL Player Data Enrichment Pipeline

Fetches daily games, maps players to matchups, and enriches with:
- Team rosters and player metadata
- Starting goaltender information
- Line number inference (workaround for missing line_combinations endpoint)
- Recent game performance data
- Opponent defensive stats
- Situational factors (B2B fatigue, road trips, etc.)
"""
import os
from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from nhl_isolated.providers.cached_provider import CachedNHLProvider
from nhl_isolated.analytics.situational_analyzer import ScheduleAnalyzer, calculate_situational_score


class NHLEnrichmentPipeline:
    """
    Enriches player data for the daily slate of NHL games.

    Handles:
    1. Fetching daily schedule and identifying teams playing
    2. Getting rosters for teams in action
    3. Filtering to active skaters (not goalies, not injured)
    4. Inferring line numbers from season stats (games started, ice time)
    5. Identifying opposing goalies
    6. Fetching recent game logs for form calculation
    """

    def __init__(self, provider: Optional[CachedNHLProvider] = None):
        """
        Initialize enrichment pipeline.

        Args:
            provider: Cached NHL data provider. Creates one if not provided.
        """
        self.provider = provider or CachedNHLProvider()
        self.current_season: Optional[str] = None
        self.schedule_analyzer: Optional[ScheduleAnalyzer] = None

    def _get_current_season(self) -> str:
        """Get current season string (e.g., '2026')."""
        if self.current_season is None:
            season_info = self.provider.get_current_season()
            self.current_season = str(season_info.get('Season', '2026'))
        return self.current_season

    def get_daily_games(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch games scheduled for the given date.

        Returns only games with Status='Scheduled' (not started yet).
        """
        games = self.provider.get_games_by_date(game_date)

        # Filter to scheduled games only
        scheduled_games = [g for g in games if g.get('Status') == 'Scheduled']
        print(f"[Enrichment] Found {len(scheduled_games)} scheduled games for {game_date}")

        return scheduled_games

    def get_teams_playing(self, games: List[Dict[str, Any]]) -> List[str]:
        """Extract unique team abbreviations from games."""
        teams = set()
        for game in games:
            teams.add(game.get('HomeTeam'))
            teams.add(game.get('AwayTeam'))
        teams.discard(None)
        return list(teams)

    def get_team_rosters(self, teams: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch rosters for multiple teams.

        Returns:
            Dict mapping team abbreviation to list of players.
        """
        rosters = {}
        for team in teams:
            roster = self.provider.get_team_roster(team)
            # Filter to active players only
            active_roster = [p for p in roster if p.get('Status') == 'Active']
            rosters[team] = active_roster
            print(f"[Enrichment] {team}: {len(active_roster)} active players")
        return rosters

    def get_starting_goalies(self, game_date: date) -> Dict[int, Dict[str, Any]]:
        """
        Get starting goaltenders for the date.

        Returns:
            Dict mapping GameID to goalie info for each team.
        """
        goalies = self.provider.get_starting_goaltenders(game_date)

        # Index by game ID
        goalie_map = {}
        for g in goalies:
            game_id = g.get('GameID')
            if game_id:
                if game_id not in goalie_map:
                    goalie_map[game_id] = {}
                team = g.get('Team')
                goalie_map[game_id][team] = g

        print(f"[Enrichment] Found starting goalies for {len(goalie_map)} games")
        return goalie_map

    def infer_goalie_starter(self, team_roster: List[Dict[str, Any]],
                             season_stats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Infer likely starting goalie when StartingGoaltenders endpoint is empty.

        Strategy:
        1. Find goalies on roster
        2. Look at season stats (Games, Started) to identify starter
        3. Return goalie with most starts

        Args:
            team_roster: Team's active roster
            season_stats: All player season stats

        Returns:
            Most likely starting goalie info, or None
        """
        # Get goalies from roster
        goalies = [p for p in team_roster if p.get('Position') == 'G']

        if not goalies:
            return None

        # Create lookup of season stats by player ID
        stats_by_id = {s['PlayerID']: s for s in season_stats if s.get('Position') == 'G'}

        # Find goalie with most starts
        best_goalie = None
        most_starts = -1

        for goalie in goalies:
            player_id = goalie.get('PlayerID')
            stats = stats_by_id.get(player_id, {})
            starts = stats.get('Started', 0)

            if starts > most_starts:
                most_starts = starts

                # Calculate save percentage
                shots_against = stats.get('GoaltendingShotsAgainst', 0) or 0
                saves = stats.get('GoaltendingSaves', 0) or 0
                sv_pct = saves / shots_against if shots_against > 0 else None

                # Calculate GAA: (Goals Against / Minutes Played) * 60
                goals_against = stats.get('GoaltendingGoalsAgainst', 0) or 0
                goalie_minutes = stats.get('GoaltendingMinutes', 0) or 0
                gaa = (goals_against / goalie_minutes) * 60 if goalie_minutes > 0 else None

                best_goalie = {
                    'PlayerID': player_id,
                    'Name': f"{goalie.get('FirstName', '')} {goalie.get('LastName', '')}".strip(),
                    'Team': goalie.get('Team'),
                    'Position': 'G',
                    'Started': starts,
                    'Games': stats.get('Games', 0),
                    'SavePercentage': round(sv_pct, 3) if sv_pct else None,
                    'GoalsAgainstAverage': round(gaa, 2) if gaa else None,
                    'Inferred': True  # Flag that this was inferred, not confirmed
                }

        return best_goalie

    def infer_line_numbers(self, team_roster: List[Dict[str, Any]],
                           season_stats: List[Dict[str, Any]]) -> Dict[int, int]:
        """
        Infer line numbers for skaters based on ice time and usage.

        Since line_combinations endpoint returns 404, we use season stats:
        - Sort skaters by average ice time (Minutes / Games)
        - Assign line 1 to top 3 forwards, line 2 to next 3, etc.
        - Assign pair 1 to top 2 defensemen, pair 2 to next 2, etc.

        Args:
            team_roster: Team's active roster (skaters only)
            season_stats: All player season stats

        Returns:
            Dict mapping PlayerID to line number (1-4)
        """
        # Create stats lookup
        stats_by_id = {s['PlayerID']: s for s in season_stats}

        # Separate forwards and defensemen
        forwards = []
        defensemen = []

        for player in team_roster:
            position = player.get('Position', '')
            if position == 'G':
                continue

            player_id = player.get('PlayerID')
            stats = stats_by_id.get(player_id, {})
            games = stats.get('Games', 0)
            minutes = stats.get('Minutes', 0)

            # Calculate average ice time
            avg_toi = minutes / games if games > 0 else 0

            player_info = {
                'PlayerID': player_id,
                'Position': position,
                'AvgTOI': avg_toi,
                'Games': games,
                'Points': (stats.get('Goals', 0) or 0) + (stats.get('Assists', 0) or 0)
            }

            if position in ['C', 'LW', 'RW']:
                forwards.append(player_info)
            elif position == 'D':
                defensemen.append(player_info)

        # Sort by average ice time (descending)
        forwards.sort(key=lambda x: x['AvgTOI'], reverse=True)
        defensemen.sort(key=lambda x: x['AvgTOI'], reverse=True)

        # Assign line numbers
        line_assignments = {}

        # Forwards: 3 per line
        for i, fwd in enumerate(forwards):
            line_num = min((i // 3) + 1, 4)  # Cap at 4th line
            line_assignments[fwd['PlayerID']] = line_num

        # Defensemen: 2 per pair, treat as "lines"
        for i, d in enumerate(defensemen):
            pair_num = min((i // 2) + 1, 3)  # Cap at 3rd pair
            line_assignments[d['PlayerID']] = pair_num

        return line_assignments

    def infer_power_play_unit(self, team_roster: List[Dict[str, Any]],
                               season_stats: List[Dict[str, Any]]) -> Dict[int, int]:
        """
        Infer power play unit assignments based on PP production.

        Strategy:
        - PP1: Top 5 players by PowerPlayGoals + PowerPlayAssists
        - PP2: Next 5 players
        - 0: Not on PP

        Returns:
            Dict mapping PlayerID to PP unit (0, 1, or 2)
        """
        stats_by_id = {s['PlayerID']: s for s in season_stats}

        pp_production = []
        for player in team_roster:
            if player.get('Position') == 'G':
                continue

            player_id = player.get('PlayerID')
            stats = stats_by_id.get(player_id, {})

            pp_goals = stats.get('PowerPlayGoals', 0) or 0
            pp_assists = stats.get('PowerPlayAssists', 0) or 0
            pp_points = pp_goals + pp_assists

            pp_production.append({
                'PlayerID': player_id,
                'PPPoints': pp_points
            })

        # Sort by PP points
        pp_production.sort(key=lambda x: x['PPPoints'], reverse=True)

        # Assign PP units
        pp_assignments = {}
        for i, player in enumerate(pp_production):
            if i < 5:
                pp_assignments[player['PlayerID']] = 1  # PP1
            elif i < 10:
                pp_assignments[player['PlayerID']] = 2  # PP2
            else:
                pp_assignments[player['PlayerID']] = 0  # Not on PP

        return pp_assignments

    def build_player_game_entries(self, games: List[Dict[str, Any]],
                                   rosters: Dict[str, List[Dict[str, Any]]],
                                   goalie_map: Dict[int, Dict[str, Any]],
                                   season_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build enriched player entries for all skaters in today's games.

        Args:
            games: List of scheduled games
            rosters: Dict of team -> roster
            goalie_map: Dict of game_id -> {team: goalie_info}
            season_stats: All player season stats

        Returns:
            List of enriched player dictionaries
        """
        players = []
        season = self._get_current_season()

        for game in games:
            game_id = game.get('GameID')
            game_time = game.get('DateTime')
            home_team = game.get('HomeTeam')
            away_team = game.get('AwayTeam')

            # Process both home and away teams
            for team, opponent, is_home in [
                (home_team, away_team, True),
                (away_team, home_team, False)
            ]:
                roster = rosters.get(team, [])
                if not roster:
                    print(f"[Enrichment] Warning: No roster for {team}")
                    continue

                # Get opposing goalie
                opposing_goalie = None
                if game_id in goalie_map:
                    opposing_goalie = goalie_map[game_id].get(opponent)

                # If no confirmed goalie, try to infer
                if not opposing_goalie:
                    opp_roster = rosters.get(opponent, [])
                    opposing_goalie = self.infer_goalie_starter(opp_roster, season_stats)

                # Infer line numbers and PP units for this team
                line_numbers = self.infer_line_numbers(roster, season_stats)
                pp_units = self.infer_power_play_unit(roster, season_stats)

                # Create stats lookup
                stats_by_id = {s['PlayerID']: s for s in season_stats}

                # Build player entries (skaters only)
                for player in roster:
                    position = player.get('Position')
                    if position == 'G':
                        continue  # Skip goalies

                    player_id = player.get('PlayerID')
                    stats = stats_by_id.get(player_id, {})

                    player_entry = {
                        # Identity
                        'player_id': player_id,
                        'player_name': f"{player.get('FirstName', '')} {player.get('LastName', '')}".strip(),
                        'team': team,
                        'position': position,

                        # Game context
                        'game_id': game_id,
                        'game_time': game_time,
                        'opponent': opponent,
                        'is_home': is_home,

                        # Line info (inferred)
                        'line_number': line_numbers.get(player_id, 4),
                        'pp_unit': pp_units.get(player_id, 0),

                        # Opposing goalie
                        'opposing_goalie_id': opposing_goalie.get('PlayerID') if opposing_goalie else None,
                        'opposing_goalie_name': opposing_goalie.get('Name') if opposing_goalie else None,
                        'opposing_goalie_sv_pct': opposing_goalie.get('SavePercentage') if opposing_goalie else None,
                        'opposing_goalie_gaa': opposing_goalie.get('GoalsAgainstAverage') if opposing_goalie else None,
                        'goalie_confirmed': not (opposing_goalie.get('Inferred', False) if opposing_goalie else True),

                        # Season stats snapshot
                        'season_games': stats.get('Games', 0),
                        'season_goals': round(stats.get('Goals', 0) or 0),
                        'season_assists': round(stats.get('Assists', 0) or 0),
                        'season_points': round((stats.get('Goals', 0) or 0) + (stats.get('Assists', 0) or 0)),
                        'season_pp_goals': round(stats.get('PowerPlayGoals', 0) or 0),
                        'season_pp_assists': round(stats.get('PowerPlayAssists', 0) or 0),
                        'season_plus_minus': round(stats.get('PlusMinus', 0) or 0),
                        'avg_toi_minutes': (stats.get('Minutes', 0) or 0) / max(stats.get('Games', 1), 1),

                        # Metadata
                        'analysis_date': game.get('Day', '').split('T')[0] if game.get('Day') else None,
                        'season': season,
                    }

                    players.append(player_entry)

        print(f"[Enrichment] Built {len(players)} player entries")
        return players

    def enrich_with_game_logs(self, players: List[Dict[str, Any]],
                               num_games: int = 10) -> List[Dict[str, Any]]:
        """
        Enrich players with recent game log data.

        This is the most API-intensive step - one call per player.
        Uses caching aggressively.

        Args:
            players: List of player entries
            num_games: Number of recent games to fetch

        Returns:
            Players with game_logs field added
        """
        season = self._get_current_season()

        for i, player in enumerate(players):
            player_id = player['player_id']

            # Fetch game logs
            logs = self.provider.get_player_game_logs(player_id, season, num_games)

            # Calculate recent form metrics
            if logs:
                recent_goals = sum(round(g.get('Goals', 0) or 0) for g in logs)
                recent_assists = sum(round(g.get('Assists', 0) or 0) for g in logs)
                recent_points = recent_goals + recent_assists
                games_played = len(logs)

                # PPG (points per game)
                ppg = recent_points / games_played if games_played > 0 else 0

                # Streak calculation (consecutive games with point)
                streak = 0
                for log in reversed(logs):
                    pts = round((log.get('Goals', 0) or 0) + (log.get('Assists', 0) or 0))
                    if pts >= 1:
                        streak += 1
                    else:
                        break

                player['game_logs'] = logs
                player['recent_games'] = games_played
                player['recent_goals'] = recent_goals
                player['recent_assists'] = recent_assists
                player['recent_points'] = recent_points
                player['recent_ppg'] = round(ppg, 3)
                player['point_streak'] = streak
            else:
                player['game_logs'] = []
                player['recent_games'] = 0
                player['recent_goals'] = 0
                player['recent_assists'] = 0
                player['recent_points'] = 0
                player['recent_ppg'] = 0.0
                player['point_streak'] = 0

            # Progress indicator
            if (i + 1) % 50 == 0:
                print(f"[Enrichment] Processed game logs for {i + 1}/{len(players)} players")

        print(f"[Enrichment] Completed game log enrichment for {len(players)} players")
        return players

    def initialize_schedule_analyzer(self, game_date: date, lookback_days: int = 7,
                                      lookahead_days: int = 3) -> None:
        """
        Initialize the schedule analyzer with a date range around the game date.

        Args:
            game_date: Target game date
            lookback_days: Days to look back for B2B detection
            lookahead_days: Days to look ahead (for context)
        """
        self.schedule_analyzer = ScheduleAnalyzer(self.provider)

        start_date = game_date - timedelta(days=lookback_days)
        end_date = game_date + timedelta(days=lookahead_days)

        print(f"[Enrichment] Loading schedule from {start_date} to {end_date}...")
        self.schedule_analyzer.load_schedule_range(start_date, end_date)

    def enrich_with_situational(self, players: List[Dict[str, Any]],
                                 game_date: date) -> List[Dict[str, Any]]:
        """
        Enrich players with situational factors (B2B, road trips, etc.).

        Args:
            players: List of player entries
            game_date: Date of the games

        Returns:
            Players with situational_score and situational_details added
        """
        if self.schedule_analyzer is None:
            self.initialize_schedule_analyzer(game_date)

        b2b_count = 0
        for player in players:
            result = calculate_situational_score(
                player,
                self.schedule_analyzer,
                game_date
            )

            player['situational_score'] = result['situational_score']
            player['situational_details'] = result['situational_details']

            # Track B2B for summary
            if result['situational_details'].get('is_b2b'):
                b2b_count += 1

        unique_teams_b2b = set(
            p['team'] for p in players
            if p.get('situational_details', {}).get('is_b2b')
        )
        print(f"[Enrichment] B2B situation detected for {len(unique_teams_b2b)} teams ({b2b_count} players)")

        return players

    def run(self, game_date: date, include_game_logs: bool = True,
            include_situational: bool = True) -> List[Dict[str, Any]]:
        """
        Run the full enrichment pipeline for a date.

        Args:
            game_date: Date to process
            include_game_logs: Whether to fetch individual game logs (API intensive)
            include_situational: Whether to include B2B/fatigue analysis

        Returns:
            List of fully enriched player dictionaries
        """
        print(f"\n{'='*60}")
        print(f"NHL ENRICHMENT PIPELINE - {game_date}")
        print(f"{'='*60}\n")

        # Step 1: Get games
        games = self.get_daily_games(game_date)
        if not games:
            print("[Enrichment] No scheduled games found")
            return []

        # Step 2: Get teams playing
        teams = self.get_teams_playing(games)
        print(f"[Enrichment] Teams playing: {teams}")

        # Step 3: Get rosters
        rosters = self.get_team_rosters(teams)

        # Step 4: Get starting goalies
        goalie_map = self.get_starting_goalies(game_date)

        # Step 5: Get season stats (for line inference and form calculation)
        season = self._get_current_season()
        season_stats = self.provider.get_player_season_stats(season)

        # Step 6: Build player entries
        players = self.build_player_game_entries(games, rosters, goalie_map, season_stats)

        # Step 7: Enrich with game logs (optional - API intensive)
        if include_game_logs:
            players = self.enrich_with_game_logs(players)

        # Step 8: Enrich with situational factors (B2B, road trips, etc.)
        if include_situational:
            players = self.enrich_with_situational(players, game_date)

        # Print provider stats
        stats = self.provider.get_stats()
        print(f"\n[Enrichment] Provider stats: {stats}")

        return players


def main():
    """Test the enrichment pipeline."""
    from dotenv import load_dotenv
    import json

    # Load environment
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env.local')
    load_dotenv(env_path)

    # Run pipeline
    pipeline = NHLEnrichmentPipeline()
    today = date.today()

    # First run without game logs (faster, for testing structure)
    print("Running enrichment WITHOUT game logs (structure test)...")
    players = pipeline.run(today, include_game_logs=False)

    if players:
        # Save sample output
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'pipeline_output')
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, f'enriched_players_{today}.json')
        with open(output_path, 'w') as f:
            # Don't include game_logs in output (too large)
            output_players = [{k: v for k, v in p.items() if k != 'game_logs'} for p in players]
            json.dump(output_players, f, indent=2, default=str)

        print(f"\nSaved {len(players)} players to {output_path}")

        # Show sample
        print("\nSample player entry:")
        sample = {k: v for k, v in players[0].items() if k != 'game_logs'}
        print(json.dumps(sample, indent=2, default=str))

    return players


if __name__ == '__main__':
    main()
