#!/usr/bin/env python3
# nhl_isolated/scripts/backfill_predictions.py
"""
Backfill NHL Predictions for Historical Games

This script generates predictions for historical dates where games have already
been completed. Useful for:
1. Testing the settlement pipeline
2. Calibrating algorithm weights based on actual hit rates
3. Building historical performance data

Usage:
    python backfill_predictions.py 2025-11-01 2025-11-23  # Date range
    python backfill_predictions.py 2025-11-15            # Single date
    python backfill_predictions.py --days 30             # Last N days
"""
import os
import sys
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nhl_isolated.providers.cached_provider import CachedNHLProvider
from nhl_isolated.analytics.matchup_analyzer import SvGAnalyzer, calculate_matchup_batch
from nhl_isolated.analytics.final_score_calculator import calculate_final_scores_batch
from nhl_isolated.analytics.situational_analyzer import ScheduleAnalyzer, calculate_situational_score
from nhl_isolated.database.db_manager import NHLDBManager


class HistoricalPredictionGenerator:
    """
    Generates predictions for historical dates with completed games.

    Unlike the normal pipeline which only looks at Scheduled games,
    this accepts games with any status (Final, F/OT, F/SO, etc.)
    """

    def __init__(self, load_svg: bool = True):
        """
        Initialize the generator.

        Args:
            load_svg: Whether to load historical SvG data
        """
        self.provider = CachedNHLProvider()
        self.db = NHLDBManager()
        self.svg_analyzer = None

        if load_svg:
            print("[Backfill] Loading historical SvG data...")
            self.svg_analyzer = SvGAnalyzer(self.provider)
            self.svg_analyzer.build_svg_from_seasons(['2025'])
            print(f"[Backfill] Loaded {self.svg_analyzer.get_summary_stats()['total_matchups']} matchups")

    def generate_for_date(self, target_date: date, save_to_db: bool = True) -> Dict[str, Any]:
        """
        Generate predictions for a single historical date.

        Args:
            target_date: Date to generate predictions for
            save_to_db: Whether to save to database

        Returns:
            Dictionary with generation results
        """
        print(f"\n[Backfill] Processing {target_date}...")

        # Get games (including completed ones)
        games = self.provider.get_games_by_date(target_date)

        # Filter to games that were played (Final, F/OT, F/SO)
        completed_statuses = ['Final', 'F/OT', 'F/SO', 'Scheduled', 'InProgress']
        playable_games = [g for g in games if g.get('Status') in completed_statuses]

        if not playable_games:
            print(f"[Backfill] No games found for {target_date}")
            return {'date': str(target_date), 'games': 0, 'players': 0}

        print(f"[Backfill] Found {len(playable_games)} games")

        # Get season stats for line inference
        season = self._get_season_for_date(target_date)
        season_stats = self.provider.get_player_season_stats(season)
        stats_by_id = {s['PlayerID']: s for s in season_stats}

        # Build player entries
        players = []
        for game in playable_games:
            game_players = self._build_game_players(game, stats_by_id, target_date)
            players.extend(game_players)

        if not players:
            print(f"[Backfill] No players found for {target_date}")
            return {'date': str(target_date), 'games': len(playable_games), 'players': 0}

        print(f"[Backfill] Built {len(players)} player entries")

        # Enrich with game logs (for recent form)
        players = self._enrich_with_game_logs(players, target_date, season)

        # Enrich with situational factors
        players = self._enrich_with_situational(players, target_date)

        # Calculate matchup scores
        if self.svg_analyzer:
            players = calculate_matchup_batch(players, self.svg_analyzer)
        else:
            # No SvG - use fallback
            for p in players:
                p['matchup_score'] = p.get('goalie_weakness_score', 0.5)
                p['matchup_details'] = {'method': 'goalie_weakness_proxy'}

        # Calculate final scores
        players = calculate_final_scores_batch(players)

        # Save to database
        if save_to_db:
            self.db.create_tables()
            self.db.upsert_predictions(players, target_date)
            print(f"[Backfill] Saved {len(players)} predictions")

        return {
            'date': str(target_date),
            'games': len(playable_games),
            'players': len(players),
            'top_5': [
                {'name': p['player_name'], 'team': p['team'], 'score': p['final_score']}
                for p in players[:5]
            ]
        }

    def _get_season_for_date(self, game_date: date) -> str:
        """Determine season string for a given date."""
        # NHL season runs Oct-Jun
        # Season "2026" = 2025-26 season (Oct 2025 - Jun 2026)
        if game_date.month >= 10:
            return str(game_date.year + 1)
        else:
            return str(game_date.year)

    def _build_game_players(self, game: Dict, stats_by_id: Dict,
                           target_date: date) -> List[Dict[str, Any]]:
        """Build player entries for a single game."""
        players = []

        game_id = game.get('GameID')
        home_team = game.get('HomeTeam')
        away_team = game.get('AwayTeam')
        game_time = game.get('DateTime')
        season = self._get_season_for_date(target_date)

        # Get opposing goalies (infer from season stats)
        home_goalie = self._infer_starting_goalie(home_team, stats_by_id)
        away_goalie = self._infer_starting_goalie(away_team, stats_by_id)

        for team, opponent, is_home, opp_goalie in [
            (home_team, away_team, True, away_goalie),
            (away_team, home_team, False, home_goalie)
        ]:
            roster = self.provider.get_team_roster(team)

            # Infer line numbers and PP units
            line_numbers = self._infer_line_numbers(roster, stats_by_id)
            pp_units = self._infer_pp_units(roster, stats_by_id)

            for player in roster:
                position = player.get('Position')
                if position == 'G' or player.get('Status') != 'Active':
                    continue

                player_id = player.get('PlayerID')
                stats = stats_by_id.get(player_id, {})

                games_played = stats.get('Games', 0) or 0
                minutes = stats.get('Minutes', 0) or 0
                avg_toi = minutes / games_played if games_played > 0 else 0

                # Calculate goalie weakness score
                goalie_sv_pct = opp_goalie.get('save_pct', 0.910) if opp_goalie else 0.910
                goalie_gaa = opp_goalie.get('gaa', 2.80) if opp_goalie else 2.80

                # Weakness score: lower SV% and higher GAA = more weakness
                sv_weakness = (0.920 - goalie_sv_pct) / 0.040  # 0.880=1.0, 0.920=0.0
                gaa_weakness = (goalie_gaa - 2.0) / 2.0  # 2.0=0.0, 4.0=1.0
                goalie_weakness = max(0, min(1, (sv_weakness + gaa_weakness) / 2 + 0.5))

                entry = {
                    'player_id': player_id,
                    'player_name': f"{player.get('FirstName', '')} {player.get('LastName', '')}".strip(),
                    'team': team,
                    'position': position,
                    'game_id': game_id,
                    'game_time': game_time,
                    'opponent': opponent,
                    'is_home': is_home,
                    'line_number': line_numbers.get(player_id, 4),
                    'pp_unit': pp_units.get(player_id, 0),
                    'avg_toi_minutes': avg_toi,
                    'opposing_goalie_id': opp_goalie.get('player_id') if opp_goalie else None,
                    'opposing_goalie_name': opp_goalie.get('name') if opp_goalie else 'Unknown',
                    'opposing_goalie_sv_pct': goalie_sv_pct,
                    'opposing_goalie_gaa': goalie_gaa,
                    'goalie_confirmed': False,
                    'goalie_weakness_score': goalie_weakness,
                    'season': season,
                    'analysis_date': str(target_date),
                }
                players.append(entry)

        return players

    def _infer_starting_goalie(self, team: str, stats_by_id: Dict) -> Optional[Dict]:
        """Infer the starting goalie for a team based on starts."""
        roster = self.provider.get_team_roster(team)
        goalies = [p for p in roster if p.get('Position') == 'G']

        if not goalies:
            return None

        best_goalie = None
        most_starts = -1

        for goalie in goalies:
            player_id = goalie.get('PlayerID')
            stats = stats_by_id.get(player_id, {})
            starts = stats.get('Started', 0) or 0

            if starts > most_starts:
                most_starts = starts

                shots_against = stats.get('GoaltendingShotsAgainst', 0) or 0
                saves = stats.get('GoaltendingSaves', 0) or 0
                goals_against = stats.get('GoaltendingGoalsAgainst', 0) or 0
                minutes = stats.get('GoaltendingMinutes', 0) or 0

                sv_pct = saves / shots_against if shots_against > 0 else 0.910
                gaa = (goals_against / minutes) * 60 if minutes > 0 else 2.80

                best_goalie = {
                    'player_id': player_id,
                    'name': f"{goalie.get('FirstName', '')} {goalie.get('LastName', '')}".strip(),
                    'save_pct': sv_pct,
                    'gaa': gaa,
                    'starts': starts,
                }

        return best_goalie

    def _infer_line_numbers(self, roster: List[Dict], stats_by_id: Dict) -> Dict[int, int]:
        """Infer line numbers based on ice time."""
        forwards = []
        defensemen = []

        for player in roster:
            position = player.get('Position', '')
            if position == 'G':
                continue

            player_id = player.get('PlayerID')
            stats = stats_by_id.get(player_id, {})
            games = stats.get('Games', 0) or 0
            minutes = stats.get('Minutes', 0) or 0
            avg_toi = minutes / games if games > 0 else 0

            info = {'PlayerID': player_id, 'AvgTOI': avg_toi}

            if position in ['C', 'LW', 'RW']:
                forwards.append(info)
            elif position == 'D':
                defensemen.append(info)

        forwards.sort(key=lambda x: x['AvgTOI'], reverse=True)
        defensemen.sort(key=lambda x: x['AvgTOI'], reverse=True)

        assignments = {}
        for i, fwd in enumerate(forwards):
            assignments[fwd['PlayerID']] = min((i // 3) + 1, 4)
        for i, d in enumerate(defensemen):
            assignments[d['PlayerID']] = min((i // 2) + 1, 3)

        return assignments

    def _infer_pp_units(self, roster: List[Dict], stats_by_id: Dict) -> Dict[int, int]:
        """Infer power play units based on PP production."""
        pp_production = []

        for player in roster:
            if player.get('Position') == 'G':
                continue

            player_id = player.get('PlayerID')
            stats = stats_by_id.get(player_id, {})
            pp_points = (stats.get('PowerPlayGoals', 0) or 0) + (stats.get('PowerPlayAssists', 0) or 0)
            pp_production.append({'PlayerID': player_id, 'PPPoints': pp_points})

        pp_production.sort(key=lambda x: x['PPPoints'], reverse=True)

        assignments = {}
        for i, player in enumerate(pp_production):
            if i < 5:
                assignments[player['PlayerID']] = 1
            elif i < 10:
                assignments[player['PlayerID']] = 2
            else:
                assignments[player['PlayerID']] = 0

        return assignments

    def _enrich_with_game_logs(self, players: List[Dict], target_date: date,
                               season: str) -> List[Dict]:
        """Enrich players with recent game log data."""
        for player in players:
            player_id = player['player_id']
            logs = self.provider.get_player_game_logs(player_id, season, num_games=10)

            # Filter to games BEFORE target date (to simulate prediction timing)
            logs = [l for l in logs if l.get('Day', '').split('T')[0] < str(target_date)]

            if logs:
                recent_goals = sum(round(g.get('Goals', 0) or 0) for g in logs)
                recent_assists = sum(round(g.get('Assists', 0) or 0) for g in logs)
                recent_points = recent_goals + recent_assists
                games_played = len(logs)
                ppg = recent_points / games_played if games_played > 0 else 0

                # Calculate streak
                streak = 0
                for log in reversed(logs):
                    pts = round((log.get('Goals', 0) or 0) + (log.get('Assists', 0) or 0))
                    if pts >= 1:
                        streak += 1
                    else:
                        break

                player['recent_games'] = games_played
                player['recent_goals'] = recent_goals
                player['recent_assists'] = recent_assists
                player['recent_points'] = recent_points
                player['recent_ppg'] = round(ppg, 3)
                player['point_streak'] = streak
            else:
                player['recent_games'] = 0
                player['recent_goals'] = 0
                player['recent_assists'] = 0
                player['recent_points'] = 0
                player['recent_ppg'] = 0.0
                player['point_streak'] = 0

        return players

    def _enrich_with_situational(self, players: List[Dict], target_date: date) -> List[Dict]:
        """Enrich players with situational factors."""
        # Initialize schedule analyzer
        schedule_analyzer = ScheduleAnalyzer(self.provider)
        start_date = target_date - timedelta(days=7)
        end_date = target_date + timedelta(days=3)
        schedule_analyzer.load_schedule_range(start_date, end_date)

        for player in players:
            result = calculate_situational_score(player, schedule_analyzer, target_date)
            player['situational_score'] = result['situational_score']
            player['situational_details'] = result['situational_details']

        return players

    def generate_date_range(self, start_date: date, end_date: date,
                           save_to_db: bool = True) -> Dict[str, Any]:
        """
        Generate predictions for a range of dates.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            save_to_db: Whether to save to database

        Returns:
            Aggregated results
        """
        results = []
        current = start_date

        while current <= end_date:
            result = self.generate_for_date(current, save_to_db=save_to_db)
            results.append(result)
            current += timedelta(days=1)

        total_games = sum(r.get('games', 0) for r in results)
        total_players = sum(r.get('players', 0) for r in results)

        return {
            'start_date': str(start_date),
            'end_date': str(end_date),
            'days_processed': len(results),
            'total_games': total_games,
            'total_players': total_players,
            'daily_results': results,
        }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Backfill NHL predictions for historical dates')
    parser.add_argument('start_date', nargs='?', help='Start date (YYYY-MM-DD)')
    parser.add_argument('end_date', nargs='?', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Generate for last N days')
    parser.add_argument('--no-db', action='store_true', help='Skip database save')
    parser.add_argument('--no-svg', action='store_true', help='Skip SvG data loading')

    args = parser.parse_args()

    # Determine date range
    if args.days:
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=args.days - 1)
    elif args.start_date:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date) if args.end_date else start_date
    else:
        # Default: yesterday only
        start_date = end_date = date.today() - timedelta(days=1)

    print(f"\n{'='*60}")
    print("NHL HISTORICAL PREDICTION BACKFILL")
    print(f"{'='*60}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Save to DB: {not args.no_db}")
    print(f"Load SvG: {not args.no_svg}")

    # Initialize generator
    generator = HistoricalPredictionGenerator(load_svg=not args.no_svg)

    # Generate predictions
    if start_date == end_date:
        result = generator.generate_for_date(start_date, save_to_db=not args.no_db)
    else:
        result = generator.generate_date_range(start_date, end_date, save_to_db=not args.no_db)

    # Print summary
    print(f"\n{'='*60}")
    print("BACKFILL COMPLETE")
    print(f"{'='*60}")

    if 'daily_results' in result:
        print(f"Days processed: {result['days_processed']}")
        print(f"Total games: {result['total_games']}")
        print(f"Total predictions: {result['total_players']}")
    else:
        print(f"Date: {result['date']}")
        print(f"Games: {result['games']}")
        print(f"Predictions: {result['players']}")
        if result.get('top_5'):
            print("\nTop 5 Predictions:")
            for i, p in enumerate(result['top_5'], 1):
                print(f"  {i}. {p['name']} ({p['team']}) - Score: {p['score']:.1f}")


if __name__ == '__main__':
    main()
