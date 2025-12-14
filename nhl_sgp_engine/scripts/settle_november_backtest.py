"""
Settlement Script for November 2025 Backtest

Fetches actual box scores from NHL API and calculates hit rates
for our predictions to validate edge calculation methodology.

This is the GO/NO-GO gate for production.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import date, datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass

from providers.nhl_official_api import NHLOfficialAPI
from nhl_sgp_engine.providers.nhl_data_provider import normalize_team


@dataclass
class SettlementResult:
    """Result of settling a single prediction."""
    player_name: str
    market_key: str
    stat_type: str
    line: float
    direction: str
    edge_pct: float
    actual_value: Optional[float]
    hit: Optional[bool]  # True if OVER hit, False if UNDER hit, None if no data
    game_date: str
    matchup: str


class NovemberSettlement:
    """Settle November backtest predictions against actual results."""

    def __init__(self):
        self.nhl_api = NHLOfficialAPI()
        self.predictions: List[Dict] = []
        self.settlements: List[SettlementResult] = []
        self.box_score_cache: Dict[str, Dict] = {}  # game_id -> box_score

    def load_predictions(self, predictions_path: Path) -> int:
        """Load predictions from backtest output."""
        with open(predictions_path, 'r') as f:
            self.predictions = json.load(f)
        return len(self.predictions)

    def get_game_id_for_matchup(self, game_date: str, matchup: str) -> Optional[int]:
        """
        Find NHL game ID for a matchup on a given date.

        Args:
            game_date: YYYY-MM-DD format
            matchup: "Away Team@Home Team" format

        Returns:
            NHL game ID or None
        """
        # Parse matchup
        parts = matchup.split('@')
        if len(parts) != 2:
            return None

        away_team_full = parts[0].strip()
        home_team_full = parts[1].strip()

        away_abbrev = normalize_team(away_team_full)
        home_abbrev = normalize_team(home_team_full)

        # Get games for that date
        games = self.nhl_api.get_games_by_date(date.fromisoformat(game_date))

        for game in games:
            if game['away_team'] == away_abbrev and game['home_team'] == home_abbrev:
                return game['game_id']

        return None

    def get_box_score(self, game_id: int) -> Optional[Dict]:
        """Get box score with caching."""
        cache_key = str(game_id)
        if cache_key in self.box_score_cache:
            return self.box_score_cache[cache_key]

        box_score = self.nhl_api.get_box_score(game_id)
        if box_score:
            self.box_score_cache[cache_key] = box_score
        return box_score

    def find_player_stats(
        self,
        box_score: Dict,
        player_name: str,
    ) -> Optional[Dict]:
        """Find player stats in box score by name."""
        if not box_score or 'players' not in box_score:
            return None

        # Normalize search name
        search_name = player_name.lower().strip()

        for player in box_score['players']:
            player_box_name = (player.get('name') or '').lower().strip()

            # Exact match
            if player_box_name == search_name:
                return player

            # Last name match (handle "J. Smith" vs "John Smith")
            search_parts = search_name.split()
            box_parts = player_box_name.split()

            if len(search_parts) >= 2 and len(box_parts) >= 2:
                if search_parts[-1] == box_parts[-1]:  # Same last name
                    return player

        return None

    def get_actual_stat_value(
        self,
        player_stats: Dict,
        stat_type: str,
    ) -> Optional[float]:
        """Extract actual stat value from player stats."""
        stat_mapping = {
            'points': 'points',
            'goals': 'goals',
            'assists': 'assists',
            'shots_on_goal': 'shots',
            'blocked_shots': 'blocked_shots',
            'power_play_points': 'power_play_goals',  # We only have PP goals, not PP assists
            'total_saves': 'saves',
            'anytime_goal': 'goals',  # For goal scorer markets
            'hits': 'hits',
        }

        mapped_stat = stat_mapping.get(stat_type)
        if mapped_stat is None:
            return None

        value = player_stats.get(mapped_stat)
        if value is None:
            return None

        # Convert from string if needed
        if isinstance(value, str):
            try:
                value = float(value)
            except (ValueError, TypeError):
                return None

        return float(value)

    def settle_game_line(
        self,
        prediction: Dict,
        box_score: Dict,
    ) -> Optional[SettlementResult]:
        """Settle a game line prediction (h2h, spreads, totals)."""
        market_key = prediction.get('market_key')
        outcome_name = prediction.get('player_name')  # Team name or 'Over'
        line = prediction.get('line', 0)
        edge_pct = prediction.get('edge_pct')
        game_date = prediction.get('game_date')
        matchup = prediction.get('matchup')

        home_score = box_score.get('home_score', 0)
        away_score = box_score.get('away_score', 0)
        total_goals = home_score + away_score
        home_team = box_score.get('home_team', '')
        away_team = box_score.get('away_team', '')

        hit = None
        actual_value = None

        if market_key == 'h2h':
            # Moneyline - did selected team win?
            if home_team in outcome_name or outcome_name in matchup.split('@')[1]:
                # Home team selected
                actual_value = home_score
                hit = home_score > away_score
            else:
                # Away team selected
                actual_value = away_score
                hit = away_score > home_score

        elif market_key == 'spreads':
            # Puck line - did team cover spread?
            margin = home_score - away_score
            if home_team in outcome_name or outcome_name in matchup.split('@')[1]:
                # Home team with spread
                actual_value = margin
                hit = margin + line > 0  # line is negative for favorite
            else:
                # Away team with spread
                actual_value = -margin
                hit = -margin + line > 0

        elif market_key == 'totals':
            # Game total over/under
            actual_value = total_goals
            if 'over' in outcome_name.lower():
                hit = total_goals > line
            else:
                hit = total_goals < line

        return SettlementResult(
            player_name=outcome_name,
            market_key=market_key,
            stat_type=market_key,
            line=line,
            direction=outcome_name.lower(),
            edge_pct=edge_pct,
            actual_value=actual_value,
            hit=hit,
            game_date=game_date,
            matchup=matchup,
        )

    def settle_prediction(self, prediction: Dict) -> Optional[SettlementResult]:
        """Settle a single prediction against actual results."""
        game_date = prediction.get('game_date')
        matchup = prediction.get('matchup')
        player_name = prediction.get('player_name')
        market_key = prediction.get('market_key')
        stat_type = prediction.get('stat_type')
        line = prediction.get('line', 0.5)
        edge_pct = prediction.get('edge_pct')

        if edge_pct is None:
            return None

        # Get game ID
        game_id = self.get_game_id_for_matchup(game_date, matchup)
        if not game_id:
            return SettlementResult(
                player_name=player_name,
                market_key=market_key,
                stat_type=stat_type,
                line=line,
                direction='over',
                edge_pct=edge_pct,
                actual_value=None,
                hit=None,
                game_date=game_date,
                matchup=matchup,
            )

        # Get box score
        box_score = self.get_box_score(game_id)
        if not box_score:
            return SettlementResult(
                player_name=player_name,
                market_key=market_key,
                stat_type=stat_type,
                line=line,
                direction='over',
                edge_pct=edge_pct,
                actual_value=None,
                hit=None,
                game_date=game_date,
                matchup=matchup,
            )

        # Handle game lines differently
        if market_key in ['h2h', 'spreads', 'totals']:
            return self.settle_game_line(prediction, box_score)

        # Find player
        player_stats = self.find_player_stats(box_score, player_name)
        if not player_stats:
            return SettlementResult(
                player_name=player_name,
                market_key=market_key,
                stat_type=stat_type,
                line=line,
                direction='over',
                edge_pct=edge_pct,
                actual_value=None,
                hit=None,
                game_date=game_date,
                matchup=matchup,
            )

        # Get actual value
        actual_value = self.get_actual_stat_value(player_stats, stat_type)
        if actual_value is None:
            return SettlementResult(
                player_name=player_name,
                market_key=market_key,
                stat_type=stat_type,
                line=line,
                direction='over',
                edge_pct=edge_pct,
                actual_value=None,
                hit=None,
                game_date=game_date,
                matchup=matchup,
            )

        # Determine hit (OVER = actual > line)
        hit = actual_value > line

        return SettlementResult(
            player_name=player_name,
            market_key=market_key,
            stat_type=stat_type,
            line=line,
            direction='over',
            edge_pct=edge_pct,
            actual_value=actual_value,
            hit=hit,
            game_date=game_date,
            matchup=matchup,
        )

    def settle_all(self) -> List[SettlementResult]:
        """Settle all predictions."""
        print(f"\nSettling {len(self.predictions)} predictions...")

        for i, pred in enumerate(self.predictions):
            if i % 100 == 0:
                print(f"  Progress: {i}/{len(self.predictions)}")

            result = self.settle_prediction(pred)
            if result:
                self.settlements.append(result)

        return self.settlements

    def calculate_hit_rates(self) -> Dict:
        """Calculate hit rates by market and edge bucket."""
        results = {
            'total_settled': 0,
            'total_unsettled': 0,
            'by_market': {},
            'by_edge_bucket': {},
            'overall': {},
        }

        # Filter to settled predictions
        settled = [s for s in self.settlements if s.hit is not None]
        unsettled = [s for s in self.settlements if s.hit is None]

        results['total_settled'] = len(settled)
        results['total_unsettled'] = len(unsettled)

        if not settled:
            return results

        # Overall hit rate
        hits = sum(1 for s in settled if s.hit)
        results['overall'] = {
            'total': len(settled),
            'hits': hits,
            'hit_rate': hits / len(settled) * 100,
        }

        # By market
        by_market = defaultdict(list)
        for s in settled:
            by_market[s.market_key].append(s)

        for market, settlements in by_market.items():
            market_hits = sum(1 for s in settlements if s.hit)
            results['by_market'][market] = {
                'total': len(settlements),
                'hits': market_hits,
                'hit_rate': market_hits / len(settlements) * 100,
            }

        # By edge bucket (for settled predictions with positive edge)
        edge_buckets = {
            'negative': [],
            '0-5%': [],
            '5-10%': [],
            '10-15%': [],
            '15%+': [],
        }

        for s in settled:
            if s.edge_pct < 0:
                edge_buckets['negative'].append(s)
            elif s.edge_pct < 5:
                edge_buckets['0-5%'].append(s)
            elif s.edge_pct < 10:
                edge_buckets['5-10%'].append(s)
            elif s.edge_pct < 15:
                edge_buckets['10-15%'].append(s)
            else:
                edge_buckets['15%+'].append(s)

        for bucket, settlements in edge_buckets.items():
            if settlements:
                bucket_hits = sum(1 for s in settlements if s.hit)
                results['by_edge_bucket'][bucket] = {
                    'total': len(settlements),
                    'hits': bucket_hits,
                    'hit_rate': bucket_hits / len(settlements) * 100,
                    'avg_edge': sum(s.edge_pct for s in settlements) / len(settlements),
                }

        return results

    def print_summary(self, results: Dict):
        """Print settlement summary."""
        print("\n" + "=" * 70)
        print("SETTLEMENT RESULTS - GO/NO-GO VALIDATION")
        print("=" * 70)

        print(f"\nTotal predictions: {results['total_settled'] + results['total_unsettled']}")
        print(f"Settled: {results['total_settled']}")
        print(f"Unsettled (no data): {results['total_unsettled']}")

        if results.get('overall'):
            overall = results['overall']
            print(f"\n{'='*70}")
            print("OVERALL HIT RATE")
            print(f"{'='*70}")
            print(f"Total: {overall['total']}")
            print(f"Hits: {overall['hits']}")
            print(f"Hit Rate: {overall['hit_rate']:.1f}%")

        if results.get('by_market'):
            print(f"\n{'='*70}")
            print("HIT RATE BY MARKET")
            print(f"{'='*70}")
            print(f"{'Market':<30} | {'Total':>6} | {'Hits':>6} | {'Hit Rate':>8}")
            print("-" * 60)
            for market, stats in sorted(results['by_market'].items(), key=lambda x: x[1]['hit_rate'], reverse=True):
                print(f"{market:<30} | {stats['total']:>6} | {stats['hits']:>6} | {stats['hit_rate']:>7.1f}%")

        if results.get('by_edge_bucket'):
            print(f"\n{'='*70}")
            print("HIT RATE BY EDGE BUCKET (Critical for Go/No-Go)")
            print(f"{'='*70}")
            print(f"{'Edge Bucket':<15} | {'Total':>6} | {'Hits':>6} | {'Hit Rate':>8} | {'Avg Edge':>8}")
            print("-" * 65)

            # Order buckets
            bucket_order = ['negative', '0-5%', '5-10%', '10-15%', '15%+']
            for bucket in bucket_order:
                if bucket in results['by_edge_bucket']:
                    stats = results['by_edge_bucket'][bucket]
                    print(f"{bucket:<15} | {stats['total']:>6} | {stats['hits']:>6} | {stats['hit_rate']:>7.1f}% | {stats['avg_edge']:>7.1f}%")

            print(f"\n{'='*70}")
            print("GO/NO-GO ANALYSIS")
            print(f"{'='*70}")

            # Check if higher edge = higher hit rate
            buckets_data = results['by_edge_bucket']
            if 'negative' in buckets_data and '15%+' in buckets_data:
                neg_rate = buckets_data['negative']['hit_rate']
                high_rate = buckets_data['15%+']['hit_rate']

                if high_rate > neg_rate + 5:
                    print("✓ POSITIVE SIGNAL: Higher edge props have higher hit rates")
                    print(f"  Negative edge: {neg_rate:.1f}% vs 15%+ edge: {high_rate:.1f}%")
                elif high_rate > neg_rate:
                    print("? WEAK SIGNAL: Slight correlation between edge and hit rate")
                    print(f"  Negative edge: {neg_rate:.1f}% vs 15%+ edge: {high_rate:.1f}%")
                else:
                    print("✗ NO SIGNAL: Edge does not predict hit rate")
                    print(f"  Negative edge: {neg_rate:.1f}% vs 15%+ edge: {high_rate:.1f}%")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--predictions', type=str,
                       default='nhl_sgp_engine/data/november_backtest_detailed.json',
                       help='Path to predictions file')
    args = parser.parse_args()

    predictions_path = Path(args.predictions)
    if not predictions_path.is_absolute():
        predictions_path = Path(__file__).parent.parent.parent / predictions_path

    if not predictions_path.exists():
        print(f"Predictions file not found: {predictions_path}")
        return

    settler = NovemberSettlement()

    # Load predictions
    count = settler.load_predictions(predictions_path)
    print(f"Loaded {count} predictions")

    # Settle all
    settler.settle_all()

    # Calculate hit rates
    results = settler.calculate_hit_rates()

    # Print summary
    settler.print_summary(results)

    # Save results
    output_path = Path(__file__).parent.parent / 'data' / 'november_settlement_results.json'

    # Convert settlements to dicts for JSON
    settlements_dict = [
        {
            'player_name': s.player_name,
            'market_key': s.market_key,
            'stat_type': s.stat_type,
            'line': s.line,
            'direction': s.direction,
            'edge_pct': s.edge_pct,
            'actual_value': s.actual_value,
            'hit': s.hit,
            'game_date': s.game_date,
            'matchup': s.matchup,
        }
        for s in settler.settlements
    ]

    output = {
        'settled_at': datetime.now().isoformat(),
        'summary': results,
        'settlements': settlements_dict,
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == '__main__':
    main()
