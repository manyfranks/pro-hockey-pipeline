"""
Settlement Workflow for NHL SGP Predictions

Production workflow:
1. Fetch unsettled predictions from database
2. Get box scores from NHL API
3. Extract actual stat values
4. Compare to predictions (hit/miss)
5. Update database with settlements

Usage:
    python -m nhl_sgp_engine.scripts.settle_predictions
    python -m nhl_sgp_engine.scripts.settle_predictions --date 2025-12-14
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from providers.nhl_official_api import NHLOfficialAPI
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.providers.nhl_data_provider import normalize_team


class PredictionSettlement:
    """Settle predictions against actual game results."""

    def __init__(self):
        self.nhl_api = NHLOfficialAPI()
        self.db = NHLSGPDBManager()
        self.box_score_cache: Dict[int, Dict] = {}

    def get_game_id_for_matchup(self, game_date: date, matchup: str) -> Optional[int]:
        """Find NHL game ID for a matchup."""
        parts = matchup.split('@')
        if len(parts) != 2:
            return None

        away_abbrev = normalize_team(parts[0].strip())
        home_abbrev = normalize_team(parts[1].strip())

        games = self.nhl_api.get_games_by_date(game_date)

        for game in games:
            if game['away_team'] == away_abbrev and game['home_team'] == home_abbrev:
                return game['game_id']

        return None

    def get_box_score(self, game_id: int) -> Optional[Dict]:
        """Get box score with caching."""
        if game_id in self.box_score_cache:
            return self.box_score_cache[game_id]

        box_score = self.nhl_api.get_box_score(game_id)
        if box_score:
            self.box_score_cache[game_id] = box_score
        return box_score

    def find_player_stats(self, box_score: Dict, player_name: str) -> Optional[Dict]:
        """Find player stats in box score by name."""
        if not box_score or 'players' not in box_score:
            return None

        search_name = player_name.lower().strip()

        for player in box_score['players']:
            player_box_name = (player.get('name') or '').lower().strip()

            if player_box_name == search_name:
                return player

            # Last name match
            search_parts = search_name.split()
            box_parts = player_box_name.split()

            if len(search_parts) >= 2 and len(box_parts) >= 2:
                if search_parts[-1] == box_parts[-1]:
                    return player

        return None

    def get_actual_value(self, player_stats: Dict, stat_type: str) -> Optional[float]:
        """Extract actual stat value from player stats."""
        stat_mapping = {
            'points': 'points',
            'goals': 'goals',
            'assists': 'assists',
            'shots_on_goal': 'shots',
            'blocked_shots': 'blocked_shots',
            'power_play_points': 'power_play_goals',
            'total_saves': 'saves',
        }

        mapped_stat = stat_mapping.get(stat_type)
        if not mapped_stat:
            return None

        value = player_stats.get(mapped_stat)
        if value is None:
            return None

        return float(value)

    def settle_prediction(self, prediction: Dict) -> Optional[Dict]:
        """
        Settle a single prediction.

        Returns dict with id, actual_value, hit or None if can't settle.
        """
        game_date = prediction['game_date']
        matchup = prediction['matchup']
        player_name = prediction['player_name']
        stat_type = prediction['stat_type']
        line = float(prediction['line'])
        direction = prediction['direction']

        # Get game ID
        game_id = self.get_game_id_for_matchup(game_date, matchup)
        if not game_id:
            return None

        # Get box score
        box_score = self.get_box_score(game_id)
        if not box_score:
            return None

        # Check game is final
        if box_score.get('game_state') not in ['OFF', 'FINAL']:
            return None

        # Find player
        player_stats = self.find_player_stats(box_score, player_name)
        if not player_stats:
            return None

        # Get actual value
        actual_value = self.get_actual_value(player_stats, stat_type)
        if actual_value is None:
            return None

        # Determine hit
        if direction == 'over':
            hit = actual_value > line
        else:
            hit = actual_value < line

        return {
            'id': prediction['id'],
            'actual_value': actual_value,
            'hit': hit,
        }

    def run(self, game_date: date = None) -> Dict:
        """
        Run settlement for a specific date.

        Args:
            game_date: Date to settle (default: yesterday)

        Returns:
            Summary dict
        """
        game_date = game_date or (date.today() - timedelta(days=1))

        print("=" * 70)
        print(f"NHL SGP SETTLEMENT - {game_date}")
        print("=" * 70)

        # Get unsettled predictions for this date
        predictions = self.db.get_unsettled_predictions(game_date)

        if not predictions:
            print(f"[Settlement] No unsettled predictions for {game_date}")
            return {'settled': 0, 'game_date': str(game_date)}

        print(f"[Settlement] Found {len(predictions)} unsettled predictions")

        # Settle each prediction
        settlements = []
        skipped = 0

        for pred in predictions:
            result = self.settle_prediction(pred)
            if result:
                settlements.append(result)
            else:
                skipped += 1

        print(f"[Settlement] Settled {len(settlements)}, skipped {skipped}")

        if not settlements:
            return {'settled': 0, 'skipped': skipped, 'game_date': str(game_date)}

        # Update database
        self.db.settle_predictions(settlements)

        # Calculate stats
        hits = sum(1 for s in settlements if s['hit'])
        total = len(settlements)
        hit_rate = hits / total * 100 if total > 0 else 0

        print(f"\n{'='*70}")
        print("SETTLEMENT RESULTS")
        print(f"{'='*70}")
        print(f"Total settled: {total}")
        print(f"Hits: {hits}")
        print(f"Hit rate: {hit_rate:.1f}%")

        return {
            'game_date': str(game_date),
            'settled': total,
            'hits': hits,
            'hit_rate': hit_rate,
            'skipped': skipped,
        }


def main():
    parser = argparse.ArgumentParser(description='Settle NHL prop predictions')
    parser.add_argument('--date', type=str, help='Date to settle (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--all', action='store_true', help='Settle all unsettled predictions')
    args = parser.parse_args()

    settler = PredictionSettlement()

    if args.all:
        # Get all unsettled and group by date
        unsettled = settler.db.get_unsettled_predictions()
        dates = set(p['game_date'] for p in unsettled)
        print(f"[Settlement] Found unsettled predictions for {len(dates)} dates")

        for d in sorted(dates):
            result = settler.run(game_date=d)
            print(f"  {d}: {result['settled']} settled, {result.get('hit_rate', 0):.1f}% hit rate")
    else:
        game_date = date.fromisoformat(args.date) if args.date else (date.today() - timedelta(days=1))
        result = settler.run(game_date=game_date)

    print("\n[Settlement] Complete")


if __name__ == '__main__':
    main()
