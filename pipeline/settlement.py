# nhl_isolated/pipeline/settlement.py
"""
NHL Settlement Pipeline

Settles predictions by fetching final box scores and determining actual outcomes.

Uses NHL Official API (api-web.nhle.com) for accurate box score data.
Previously used SportsData.io which had scrambled data issues on free tier.

Settlement outcomes:
- 1: Player scored at least 1 point (HIT)
- 0: Player did not score a point (MISS)
- 2: Game postponed (PPD)
- 3: Player did not play (DNP)
"""
import os
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

from providers.nhl_official_api import NHLOfficialAPI
from database.db_manager import NHLDBManager
from utilities.logger import get_logger

logger = get_logger('settlement')


# Settlement outcome codes
OUTCOME_HIT = 1      # Got at least 1 point
OUTCOME_MISS = 0     # No points
OUTCOME_PPD = 2      # Game postponed
OUTCOME_DNP = 3      # Did not play


class SettlementPipeline:
    """
    Settles NHL predictions against actual game results.

    Usage:
        settler = SettlementPipeline()
        results = settler.settle_date(date(2025, 11, 25))
    """

    def __init__(self):
        """Initialize settlement pipeline."""
        self.api = NHLOfficialAPI()
        self.db = NHLDBManager()

    def settle_date(self, settlement_date: date, dry_run: bool = False) -> Dict[str, Any]:
        """
        Settle all predictions for a given date.

        Args:
            settlement_date: Date to settle predictions for
            dry_run: If True, don't update database (just show what would happen)

        Returns:
            Dictionary with settlement summary
        """
        print(f"\n{'='*60}")
        print(f"NHL SETTLEMENT PIPELINE - {settlement_date}")
        print(f"{'='*60}\n")

        # Step 1: Get unsettled predictions
        print("[Step 1/4] Fetching unsettled predictions...")
        unsettled = self.db.get_unsettled_predictions(settlement_date)

        if not unsettled:
            print(f"[Settlement] No unsettled predictions for {settlement_date}")
            return {
                'date': str(settlement_date),
                'predictions_found': 0,
                'settled': 0,
                'results': {}
            }

        print(f"[Settlement] Found {len(unsettled)} unsettled predictions")

        # Get unique game IDs
        game_ids = list(set(p['game_id'] for p in unsettled))
        print(f"[Settlement] Across {len(game_ids)} games")

        # Step 2: Fetch box scores for those games
        print("\n[Step 2/4] Fetching box scores...")
        box_scores = self._fetch_box_scores(settlement_date, game_ids)

        if not box_scores:
            print("[Settlement] No completed box scores found")
            return {
                'date': str(settlement_date),
                'predictions_found': len(unsettled),
                'settled': 0,
                'results': {},
                'note': 'No completed box scores available yet'
            }

        print(f"[Settlement] Retrieved {len(box_scores)} box scores")

        # Step 3: Match predictions to actual results
        print("\n[Step 3/4] Matching predictions to results...")
        settlements = self._match_results(unsettled, box_scores)

        # Count outcomes
        outcome_counts = {
            'hits': sum(1 for s in settlements if s['point_outcome'] == OUTCOME_HIT),
            'misses': sum(1 for s in settlements if s['point_outcome'] == OUTCOME_MISS),
            'dnp': sum(1 for s in settlements if s['point_outcome'] == OUTCOME_DNP),
            'ppd': sum(1 for s in settlements if s['point_outcome'] == OUTCOME_PPD),
        }

        print(f"\n[Settlement] Results:")
        print(f"  Hits (1+ point): {outcome_counts['hits']}")
        print(f"  Misses (0 pts):  {outcome_counts['misses']}")
        print(f"  DNP:             {outcome_counts['dnp']}")
        print(f"  PPD:             {outcome_counts['ppd']}")

        # Step 4: Update database
        if dry_run:
            print("\n[Step 4/4] DRY RUN - Skipping database update")
        else:
            print("\n[Step 4/4] Updating database...")
            self.db.update_settlement(settlements)
            print(f"[Settlement] Updated {len(settlements)} predictions")

        # Calculate hit rate
        valid_predictions = outcome_counts['hits'] + outcome_counts['misses']
        hit_rate = (outcome_counts['hits'] / valid_predictions * 100) if valid_predictions > 0 else 0

        result = {
            'date': str(settlement_date),
            'predictions_found': len(unsettled),
            'settled': len(settlements),
            'outcomes': outcome_counts,
            'hit_rate': round(hit_rate, 1),
            'valid_predictions': valid_predictions,
        }

        # Print summary
        self._print_settlement_summary(settlements, settlement_date)

        return result

    def _fetch_box_scores(self, game_date: date, game_ids: List[int]) -> Dict[int, Dict]:
        """
        Fetch box scores for the given game IDs using NHL Official API.

        Returns:
            Dict mapping game_id to box score data
        """
        box_scores = {}

        # First get all games for the date to check status
        try:
            games = self.api.get_games_by_date(game_date)

            # Build map of game_id -> game info
            game_info_map = {g['game_id']: g for g in games}

            for game_id in game_ids:
                game_info = game_info_map.get(game_id)

                if not game_info:
                    continue

                game_state = game_info.get('game_state', '')

                # Check if game is final (OFF = Final, FINAL = Final)
                if game_state in ['OFF', 'FINAL']:
                    # Fetch full box score
                    box = self.api.get_box_score(game_id)
                    if box:
                        box_scores[game_id] = box
                elif game_state == 'PPD':
                    box_scores[game_id] = {'status': 'Postponed'}

        except Exception as e:
            print(f"[Settlement] Error fetching box scores: {e}")

        return box_scores

    def _match_results(self, predictions: List[Dict], box_scores: Dict[int, Dict]) -> List[Dict]:
        """
        Match predictions to actual results from box scores.

        Uses NHL Official API box score format which has:
        - 'players' list with player_id, goals, assists, points, toi

        Returns:
            List of settlement dictionaries
        """
        settlements = []

        for pred in predictions:
            player_id = pred['player_id']
            game_id = pred['game_id']
            analysis_date = pred['analysis_date']

            settlement = {
                'player_id': player_id,
                'game_id': game_id,
                'analysis_date': analysis_date,
                'player_name': pred.get('player_name'),
                'rank': pred.get('rank'),
                'actual_points': None,
                'actual_goals': None,
                'actual_assists': None,
                'point_outcome': None,
            }

            # Check if we have box score for this game
            if game_id not in box_scores:
                # Game not yet complete
                continue

            box = box_scores[game_id]

            # Check for postponement
            if box.get('status') == 'Postponed':
                settlement['point_outcome'] = OUTCOME_PPD
                settlements.append(settlement)
                continue

            # Find player in box score (NHL Official API format)
            players = box.get('players', [])
            player_stats = None

            for p in players:
                if p.get('player_id') == player_id:
                    player_stats = p
                    break

            if player_stats is None:
                # Player not in box score (DNP, scratched, injured)
                settlement['point_outcome'] = OUTCOME_DNP
                settlements.append(settlement)
                continue

            # Check if player actually played (had ice time)
            # TOI format is "MM:SS" string or None
            toi = player_stats.get('toi')
            if not toi or toi == '00:00':
                settlement['point_outcome'] = OUTCOME_DNP
                settlements.append(settlement)
                continue

            # Get actual stats (NHL Official API uses lowercase field names)
            goals = player_stats.get('goals', 0) or 0
            assists = player_stats.get('assists', 0) or 0
            points = goals + assists

            settlement['actual_goals'] = goals
            settlement['actual_assists'] = assists
            settlement['actual_points'] = points
            settlement['point_outcome'] = OUTCOME_HIT if points >= 1 else OUTCOME_MISS

            settlements.append(settlement)

        return settlements

    def _print_settlement_summary(self, settlements: List[Dict], settlement_date: date):
        """Print a summary of settled predictions."""
        print(f"\n{'='*70}")
        print("SETTLEMENT SUMMARY")
        print(f"{'='*70}")

        # Sort by rank
        settlements_sorted = sorted(settlements, key=lambda x: x.get('rank', 999))

        # Show top 15 settled predictions
        print(f"\nTop 15 Predictions Settlement (by rank):")
        print("-" * 80)
        print(f"{'Rank':<5} {'Player':<25} {'Pts':>4} {'G':>3} {'A':>3} {'Outcome':<10}")
        print("-" * 80)

        for s in settlements_sorted[:15]:
            rank = s.get('rank', '?')
            name = (s.get('player_name') or 'Unknown')[:24]
            pts = s.get('actual_points')
            goals = s.get('actual_goals')
            assists = s.get('actual_assists')
            outcome = s.get('point_outcome')

            outcome_str = {
                OUTCOME_HIT: '✓ HIT',
                OUTCOME_MISS: '✗ MISS',
                OUTCOME_DNP: 'DNP',
                OUTCOME_PPD: 'PPD',
            }.get(outcome, '?')

            pts_str = str(pts) if pts is not None else '-'
            goals_str = str(goals) if goals is not None else '-'
            assists_str = str(assists) if assists is not None else '-'

            print(f"{rank:<5} {name:<25} {pts_str:>4} {goals_str:>3} {assists_str:>3} {outcome_str:<10}")

    def settle_date_range(self, start_date: date, end_date: date, dry_run: bool = False) -> Dict[str, Any]:
        """
        Settle predictions for a range of dates.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            dry_run: If True, don't update database

        Returns:
            Aggregated results
        """
        results = []
        current = start_date

        while current <= end_date:
            result = self.settle_date(current, dry_run=dry_run)
            results.append(result)
            current += timedelta(days=1)

        # Aggregate
        total_predictions = sum(r.get('valid_predictions', 0) for r in results)
        total_hits = sum(r.get('outcomes', {}).get('hits', 0) for r in results)

        return {
            'start_date': str(start_date),
            'end_date': str(end_date),
            'days_processed': len(results),
            'total_predictions': total_predictions,
            'total_hits': total_hits,
            'overall_hit_rate': round(total_hits / total_predictions * 100, 1) if total_predictions > 0 else 0,
            'daily_results': results,
        }

    def get_performance_report(self, start_date: date = None, end_date: date = None) -> Dict[str, Any]:
        """
        Generate a performance report from the database.

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Performance statistics
        """
        return self.db.get_hit_rate_summary(start_date, end_date)


def settle_predictions(settlement_date: date = None, dry_run: bool = False) -> Dict[str, Any]:
    """
    Convenience function to settle predictions.

    Args:
        settlement_date: Date to settle (default: yesterday)
        dry_run: Don't update database

    Returns:
        Settlement results
    """
    if settlement_date is None:
        settlement_date = date.today() - timedelta(days=1)

    settler = SettlementPipeline()
    return settler.settle_date(settlement_date, dry_run=dry_run)


if __name__ == '__main__':
    import sys

    # Parse arguments
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date format: {sys.argv[1]}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target = date.today() - timedelta(days=1)

    dry_run = '--dry-run' in sys.argv

    result = settle_predictions(target, dry_run=dry_run)

    print(f"\n{'='*60}")
    print("FINAL RESULTS")
    print(f"{'='*60}")
    print(f"Date: {result['date']}")
    print(f"Predictions Settled: {result.get('settled', 0)}")
    print(f"Hit Rate: {result.get('hit_rate', 0)}%")
