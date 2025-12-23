# nhl_isolated/pipeline/nhl_prediction_pipeline.py
"""
NHL Prediction Pipeline - Using Official NHL API + DailyFaceoff

This pipeline generates player point predictions using:
1. NHL Official API (api-web.nhle.com) - Accurate stats, game logs, schedules
2. DailyFaceoff.com - Line combinations and power play units

Replaces the SportsData.io-based pipeline which had scrambled data.
"""

import os
import sys
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from providers.nhl_official_api import NHLOfficialAPI
from providers.dailyfaceoff_scraper import DailyFaceoffScraper
from analytics.final_score_calculator import calculate_final_scores_batch
from analytics.goalie_weakness_calculator import calculate_goalie_weakness_score
from utilities.logger import get_logger

logger = get_logger('pipeline')


class NHLPredictionPipeline:
    """
    Generates NHL player point predictions using accurate data sources.

    Data Sources:
    - NHL Official API: Player stats, game logs, schedules, goalie stats
    - DailyFaceoff: Line combinations, power play units
    """

    OUTPUT_DIR = Path(__file__).parent.parent / "data" / "predictions"

    def __init__(self):
        """Initialize the pipeline with data providers."""
        self.nhl_api = NHLOfficialAPI()
        self.dailyfaceoff = DailyFaceoffScraper()
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def get_games_for_date(self, target_date: date) -> List[Dict]:
        """Get all games scheduled for a date."""
        return self.nhl_api.get_games_by_date(target_date)

    def get_line_info(self, player_name: str, team_abbrev: str) -> Dict:
        """
        Get line and PP info for a player from DailyFaceoff.

        Returns:
            Dict with 'line' (1-4), 'pp_unit' (0, 1, 2), and 'lineup_confirmed' (bool)
        """
        info = self.dailyfaceoff.get_player_line_info(player_name, team_abbrev)

        if info:
            return {
                'line_number': info.get('line', 4),
                'pp_unit': info.get('pp_unit', 0),
                'position': info.get('position', 'unknown'),
                'lineup_confirmed': True,  # Player is in DailyFaceoff projected lineup
            }

        # Fallback: Player not in projected lineup
        # Mark as unconfirmed - these players may be scratched
        return {
            'line_number': 4,  # Default to 4th line if not found (likely scratch)
            'pp_unit': 0,
            'position': 'unknown',
            'lineup_confirmed': False,  # NOT in DailyFaceoff lineup - may not play
        }

    def get_opposing_goalie(self, team_abbrev: str, opponent_abbrev: str) -> Dict:
        """Get the probable starting goalie for the opponent."""
        goalie = self.nhl_api.get_probable_goalie(opponent_abbrev)

        if goalie:
            return {
                'opposing_goalie_id': goalie['player_id'],
                'opposing_goalie_name': goalie['name'],
                'opposing_goalie_sv_pct': goalie.get('save_pct', 0.900),
                'opposing_goalie_gaa': goalie.get('gaa', 2.90),
                'goalie_confirmed': goalie.get('is_confirmed', False),
            }

        # Fallback
        return {
            'opposing_goalie_id': None,
            'opposing_goalie_name': 'Unknown',
            'opposing_goalie_sv_pct': 0.905,  # League average
            'opposing_goalie_gaa': 2.90,
            'goalie_confirmed': False,
        }

    def build_player_entry(
        self,
        player: Dict,
        game: Dict,
        team_abbrev: str,
        is_home: bool,
        target_date: date
    ) -> Dict:
        """Build a complete player entry for scoring."""
        player_id = player['player_id']
        player_name = player['name']

        # Get line info from DailyFaceoff
        line_info = self.get_line_info(player_name, team_abbrev)

        # Get opposing goalie
        opponent = game['home_team'] if not is_home else game['away_team']
        goalie_info = self.get_opposing_goalie(team_abbrev, opponent)

        # Get recent form from NHL API
        recent_form = self.nhl_api.calculate_recent_form(player_id, 10)

        # Build entry
        entry = {
            # Identifiers
            'player_id': player_id,
            'player_name': player_name,
            'team': team_abbrev,
            'position': player.get('position', line_info.get('position', 'C')),

            # Game info
            'game_id': game['game_id'],
            'game_date': str(target_date),
            'game_time': game.get('start_time_utc'),
            'opponent': opponent,
            'is_home': is_home,

            # Line info (from DailyFaceoff)
            'line_number': line_info['line_number'],
            'pp_unit': line_info['pp_unit'],
            'lineup_confirmed': line_info.get('lineup_confirmed', False),

            # Season stats (from get_team_stats which uses games_played, goals, etc.)
            'season_games': player.get('games_played', player.get('season_games', 0)),
            'season_goals': player.get('goals', player.get('season_goals', 0)),
            'season_assists': player.get('assists', player.get('season_assists', 0)),
            'season_points': player.get('points', player.get('season_points', 0)),
            'season_pp_goals': player.get('pp_goals', player.get('season_pp_goals', 0)),
            'avg_toi_minutes': player.get('avg_toi', player.get('avg_toi_minutes', 0)),

            # Recent form (from NHL API)
            'recent_games': recent_form['recent_games'],
            'recent_goals': recent_form['recent_goals'],
            'recent_assists': recent_form['recent_assists'],
            'recent_points': recent_form['recent_points'],
            'recent_ppg': recent_form['recent_ppg'],
            'point_streak': recent_form['point_streak'],

            # Goalie info
            **goalie_info,

            # Metadata
            'data_source': 'nhl_official_api',
            'analysis_date': str(target_date),
        }

        return entry

    def generate_predictions(
        self,
        target_date: date,
        save: bool = True,
        force_refresh: bool = False
    ) -> List[Dict]:
        """
        Generate predictions for all players in games on a given date.

        Args:
            target_date: Date to generate predictions for
            save: Whether to save results to file
            force_refresh: Force refresh all data from APIs (ignore cache)

        Returns:
            List of scored player predictions
        """
        print(f"\n{'='*70}")
        print(f"NHL Prediction Pipeline - {target_date}")
        if force_refresh:
            print("[FORCE REFRESH MODE - Fetching fresh data from all APIs]")
        print(f"{'='*70}")

        # Get games
        games = self.get_games_for_date(target_date)
        print(f"\nGames found: {len(games)}")

        if not games:
            print("No games scheduled for this date.")
            return []

        for game in games:
            print(f"  {game['away_team']} @ {game['home_team']} ({game['game_state']})")

        # Refresh DailyFaceoff cache if needed (or force refresh)
        print("\n[DailyFaceoff] Loading line combinations...")
        self.dailyfaceoff.get_all_teams(force_refresh=force_refresh)

        # Build player entries for each game
        all_players = []

        for game in games:
            # Skip completed games for predictions (but allow for backfill)
            if game['game_state'] in ['OFF', 'FINAL']:
                print(f"\n  Skipping completed game: {game['away_team']} @ {game['home_team']}")
                continue

            print(f"\n  Processing: {game['away_team']} @ {game['home_team']}")

            # Get players for both teams
            for team_abbrev, is_home in [(game['away_team'], False), (game['home_team'], True)]:
                print(f"    Loading {team_abbrev} players...", end=" ")

                # Get team stats (includes all skaters)
                team_stats = self.nhl_api.get_team_stats(team_abbrev)
                skaters = team_stats.get('skaters', [])

                print(f"Found {len(skaters)} skaters")

                for player in skaters:
                    # Skip players with 0 games (inactive/injured)
                    if player.get('games_played', 0) == 0:
                        continue

                    entry = self.build_player_entry(
                        player, game, team_abbrev, is_home, target_date
                    )

                    # Filter out unconfirmed L4 players to reduce DNP rate
                    # Only include L4 players if they're confirmed in DailyFaceoff lineup
                    if entry['line_number'] >= 4 and not entry.get('lineup_confirmed', False):
                        continue  # Skip - likely scratch

                    all_players.append(entry)

        print(f"\nTotal players to score: {len(all_players)}")

        if not all_players:
            print("No players to score.")
            return []

        # Calculate final scores
        print("\nCalculating scores...")
        scored_players = calculate_final_scores_batch(all_players)

        # Print top 10
        print(f"\n{'='*70}")
        print("TOP 10 PREDICTIONS")
        print(f"{'='*70}")
        print(f"{'Rank':<5} {'Player':<22} {'Team':<5} {'Pos':<4} {'Line':<5} {'PP':<4} {'Score':<7} {'PPG':<6} {'Flags':<20}")
        print("-" * 90)

        for i, p in enumerate(scored_players[:10], 1):
            # Show regression flags if present (makes hot streak penalties obvious)
            flags = p.get('regression_flags', [])
            flag_str = ','.join(flags) if flags else '-'
            print(f"{i:<5} {p['player_name']:<22} {p['team']:<5} {p['position']:<4} "
                  f"L{p['line_number']:<4} PP{p['pp_unit']:<3} {p['final_score']:<7.1f} {p['recent_ppg']:<6.2f} {flag_str:<20}")

        # Show any regression-adjusted players in top 25 for visibility
        regression_players = [p for p in scored_players[:25] if p.get('regression_flags')]
        if regression_players:
            print(f"\n⚠️  REGRESSION ADJUSTMENTS APPLIED ({len(regression_players)} players in top 25):")
            for p in regression_players[:3]:  # Show top 3
                print(f"   {p['player_name']}: PPG {p['recent_ppg']:.2f} → {p.get('regression_explanation', 'See regression_flags')[:80]}...")

        # Save results
        if save:
            self._save_predictions(scored_players, target_date)

        return scored_players

    def generate_predictions_for_backfill(
        self,
        target_date: date,
        include_completed: bool = True
    ) -> List[Dict]:
        """
        Generate predictions for backfill (includes completed games).

        For historical dates, we want to generate predictions even for
        completed games so we can compare against actual results.
        """
        print(f"\n{'='*70}")
        print(f"NHL Backfill Pipeline - {target_date}")
        print(f"{'='*70}")

        games = self.get_games_for_date(target_date)
        print(f"\nGames found: {len(games)}")

        if not games:
            return []

        # Refresh DailyFaceoff cache
        self.dailyfaceoff.get_all_teams()

        all_players = []

        for game in games:
            print(f"\n  Processing: {game['away_team']} @ {game['home_team']} ({game['game_state']})")

            for team_abbrev, is_home in [(game['away_team'], False), (game['home_team'], True)]:
                team_stats = self.nhl_api.get_team_stats(team_abbrev)
                skaters = team_stats.get('skaters', [])

                for player in skaters:
                    if player.get('games_played', 0) == 0:
                        continue

                    entry = self.build_player_entry(
                        player, game, team_abbrev, is_home, target_date
                    )

                    # Filter out unconfirmed L4 players (same as main generate)
                    if entry['line_number'] >= 4 and not entry.get('lineup_confirmed', False):
                        continue

                    all_players.append(entry)

        if not all_players:
            return []

        # Calculate scores
        scored_players = calculate_final_scores_batch(all_players)

        return scored_players

    def _save_predictions(self, predictions: List[Dict], target_date: date) -> None:
        """Save predictions to JSON file."""
        date_str = target_date.strftime('%Y-%m-%d')

        # Save full predictions
        full_path = self.OUTPUT_DIR / f"nhl_predictions_{date_str}_nhlapi.json"
        with open(full_path, 'w') as f:
            json.dump(predictions, f, indent=2, default=str)
        print(f"\nSaved full predictions to: {full_path}")

        # Save top 25 summary
        top_path = self.OUTPUT_DIR / f"nhl_top25_{date_str}_nhlapi.json"
        top_25 = [{
            'rank': i + 1,
            'player_name': p['player_name'],
            'team': p['team'],
            'position': p['position'],
            'opponent': p['opponent'],
            'line_number': p['line_number'],
            'pp_unit': p['pp_unit'],
            'final_score': p['final_score'],
            'recent_ppg': p['recent_ppg'],
            'confidence': p.get('confidence', 'unknown'),
        } for i, p in enumerate(predictions[:25])]

        with open(top_path, 'w') as f:
            json.dump(top_25, f, indent=2)
        print(f"Saved top 25 to: {top_path}")

    def _save_to_database(self, predictions: List[Dict], target_date: date) -> bool:
        """
        Save predictions to PostgreSQL database.

        Args:
            predictions: List of scored player predictions
            target_date: Analysis date

        Returns:
            True if successful, False otherwise
        """
        try:
            from database.db_manager import NHLDBManager

            db = NHLDBManager()

            # Ensure tables exist
            db.create_tables()

            # Transform predictions to match database schema
            db_predictions = []
            for rank, p in enumerate(predictions, 1):
                # Extract nested fields
                matchup_details = p.get('matchup_details', {})
                situational_details = p.get('situational_details', {})

                # Build component_details JSON
                component_details = {
                    'component_scores': p.get('component_scores', {}),
                    'form_details': p.get('form_details', {}),
                    'opportunity_details': p.get('opportunity_details', {}),
                    'goalie_weakness_details': p.get('goalie_weakness_details', {}),
                    'matchup_details': matchup_details,
                    'situational_details': situational_details,
                }

                db_record = {
                    # Required fields
                    'player_id': p['player_id'],
                    'game_id': p['game_id'],
                    'analysis_date': target_date,

                    # Player context
                    'player_name': p.get('player_name'),
                    'team': p.get('team'),
                    'position': p.get('position'),
                    'opponent': p.get('opponent'),
                    'is_home': p.get('is_home', False),

                    # Scores and ranking
                    'final_score': p.get('final_score'),
                    'rank': rank,
                    'confidence': p.get('confidence'),

                    # Component scores
                    'recent_form_score': p.get('recent_form_score'),
                    'line_opportunity_score': p.get('line_opportunity_score'),
                    'goalie_weakness_score': p.get('goalie_weakness_score'),
                    'matchup_score': matchup_details.get('matchup_score', p.get('matchup_score')),
                    'situational_score': situational_details.get('situational_score', p.get('situational_score')),

                    # Component details JSON
                    'component_details': component_details,

                    # Line/PP info
                    'line_number': p.get('line_number'),
                    'pp_unit': p.get('pp_unit'),
                    'avg_toi_minutes': p.get('avg_toi_minutes'),

                    # Recent form
                    'recent_ppg': p.get('recent_ppg'),
                    'recent_games': p.get('recent_games'),
                    'recent_points': p.get('recent_points'),
                    'recent_goals': p.get('recent_goals'),
                    'recent_assists': p.get('recent_assists'),
                    'point_streak': p.get('point_streak'),

                    # Opposing goalie
                    'opposing_goalie_id': p.get('opposing_goalie_id'),
                    'opposing_goalie_name': p.get('opposing_goalie_name'),
                    'opposing_goalie_sv_pct': p.get('opposing_goalie_sv_pct'),
                    'opposing_goalie_gaa': p.get('opposing_goalie_gaa'),
                    'goalie_confirmed': p.get('goalie_confirmed', False),

                    # Matchup details
                    'matchup_method': matchup_details.get('method', 'nhl_api_conditional'),

                    # Situational factors
                    'is_b2b': situational_details.get('is_b2b', False),
                    'is_b2b2b': situational_details.get('is_b2b2b', False),
                    'days_rest': situational_details.get('days_rest'),
                    'opposing_goalie_b2b': situational_details.get('opposing_goalie_b2b', False),

                    # Season stats
                    'season_games': p.get('season_games'),
                    'season_goals': p.get('season_goals'),
                    'season_assists': p.get('season_assists'),
                    'season_points': p.get('season_points'),
                    'season_pp_goals': p.get('season_pp_goals'),
                }

                db_predictions.append(db_record)

            # Upsert to database
            db.upsert_predictions(db_predictions, target_date)

            logger.info(f"Saved {len(db_predictions)} predictions to database for {target_date}")
            return True

        except Exception as e:
            logger.error(f"Error saving predictions to database: {e}")
            return False

    def _save_line_combinations_to_db(self, target_date: date) -> bool:
        """
        Save current line combinations from DailyFaceoff cache to database.

        Args:
            target_date: Date to associate with the line data

        Returns:
            True if successful, False otherwise
        """
        try:
            from database.db_manager import NHLDBManager

            # Get all team line data from cache
            line_data = self.dailyfaceoff.get_all_teams()

            if not line_data:
                logger.warning("No line combination data available")
                return False

            db = NHLDBManager()
            db.upsert_line_combinations(line_data, target_date)

            logger.info(f"Saved line combinations for {len(line_data)} teams on {target_date}")
            return True

        except Exception as e:
            logger.error(f"Error saving line combinations: {e}")
            return False

    def _save_games_to_db(self, predictions: List[Dict], target_date: date) -> bool:
        """
        Save game records to database from predictions.

        Args:
            predictions: List of predictions (used to extract game info)
            target_date: Date of the games

        Returns:
            True if successful, False otherwise
        """
        try:
            from database.db_manager import NHLDBManager

            db = NHLDBManager()

            # Build unique game records from predictions
            game_records = []
            seen_game_ids = set()

            for p in predictions:
                game_id = p.get('game_id')
                if game_id and game_id not in seen_game_ids:
                    seen_game_ids.add(game_id)
                    game_record = {
                        'game_id': game_id,
                        'home_team': p['team'] if p.get('is_home') else p.get('opponent'),
                        'away_team': p.get('opponent') if p.get('is_home') else p['team'],
                        'game_date': target_date,
                        'game_time': p.get('game_time'),
                        'season': p.get('season'),
                        'status': 'Scheduled'
                    }
                    game_records.append(game_record)

            if game_records:
                db.upsert_games(game_records)
                logger.info(f"Saved {len(game_records)} game records for {target_date}")

            return True

        except Exception as e:
            logger.error(f"Error saving games: {e}")
            return False


def main():
    """Run the prediction pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='NHL Prediction Pipeline')
    parser.add_argument('--date', type=str, help='Date to predict (YYYY-MM-DD)')
    parser.add_argument('--tomorrow', action='store_true', help='Predict for tomorrow')
    parser.add_argument('--backfill', type=str, help='Backfill date range (YYYY-MM-DD:YYYY-MM-DD)')
    parser.add_argument('--db', action='store_true', help='Save predictions to database')
    parser.add_argument('--db-only', action='store_true', help='Save to database only (no JSON)')

    args = parser.parse_args()

    pipeline = NHLPredictionPipeline()

    if args.backfill:
        # Backfill mode
        start_str, end_str = args.backfill.split(':')
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        print(f"Backfilling from {start_date} to {end_date}")
        if args.db or args.db_only:
            print("[DB] Database writes enabled")

        current = start_date
        while current <= end_date:
            try:
                predictions = pipeline.generate_predictions_for_backfill(current)
                if predictions:
                    if not args.db_only:
                        pipeline._save_predictions(predictions, current)
                    if args.db or args.db_only:
                        pipeline._save_games_to_db(predictions, current)
                        pipeline._save_to_database(predictions, current)
                        pipeline._save_line_combinations_to_db(current)
            except Exception as e:
                print(f"Error on {current}: {e}")

            current += timedelta(days=1)

    else:
        # Single date mode
        if args.tomorrow:
            target_date = date.today() + timedelta(days=1)
        elif args.date:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        predictions = pipeline.generate_predictions(target_date, save=not args.db_only)

        if predictions and (args.db or args.db_only):
            pipeline._save_games_to_db(predictions, target_date)
            pipeline._save_to_database(predictions, target_date)
            pipeline._save_line_combinations_to_db(target_date)


if __name__ == '__main__':
    main()
