"""
Backtest Engine for NHL SGP

Runs edge detection on historical data and evaluates performance.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import json

from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator, EdgeResult
from nhl_sgp_engine.signals.base import PropContext
from nhl_sgp_engine.config.settings import MIN_EDGE_PCT, DATA_DIR


@dataclass
class BacktestResult:
    """Result for a single prop backtest."""
    prop_id: int
    player_name: str
    stat_type: str
    line: float
    direction: str
    edge_pct: float
    confidence: float
    model_prob: float
    market_prob: float
    actual_value: Optional[float]
    hit: Optional[bool]
    profit: Optional[float]  # At $100 stake


@dataclass
class BacktestSummary:
    """Summary of backtest results."""
    total_props: int
    settled_props: int
    edge_props: int  # Props with edge >= threshold

    # Overall performance
    overall_hit_rate: float
    overall_roi: float

    # By edge bucket
    edge_5_10: Dict[str, float]  # hit_rate, roi, count
    edge_10_15: Dict[str, float]
    edge_15_plus: Dict[str, float]

    # By stat type
    by_stat_type: Dict[str, Dict[str, float]]

    # By direction
    over_hit_rate: float
    under_hit_rate: float


class BacktestEngine:
    """
    Runs backtests on historical NHL player props.

    Process:
    1. Load historical odds from database
    2. For each prop, build context and calculate edge
    3. Compare edge prediction to actual outcome
    4. Generate performance metrics
    """

    def __init__(self):
        self.db = NHLSGPDBManager()
        self.calculator = EdgeCalculator()
        self.results: List[BacktestResult] = []

    def run_backtest(
        self,
        start_date: str = None,
        end_date: str = None,
        min_edge: float = MIN_EDGE_PCT,
        stat_types: List[str] = None,
    ) -> BacktestSummary:
        """
        Run backtest on historical data.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            min_edge: Minimum edge % to consider
            stat_types: Filter to specific stat types

        Returns:
            BacktestSummary with performance metrics
        """
        print(f"\n{'='*60}")
        print("NHL SGP ENGINE - BACKTEST")
        print(f"{'='*60}")
        print(f"Date range: {start_date or 'all'} to {end_date or 'all'}")
        print(f"Min edge: {min_edge}%")
        print(f"Stat types: {stat_types or 'all'}")
        print(f"{'='*60}\n")

        # Load historical odds
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

        props = self._load_historical_props(start, end, stat_types)
        print(f"Loaded {len(props)} historical props")

        # Process each prop
        self.results = []
        for i, prop in enumerate(props):
            if (i + 1) % 100 == 0:
                print(f"Processing prop {i+1}/{len(props)}...")

            result = self._process_prop(prop)
            if result:
                self.results.append(result)

        print(f"\nProcessed {len(self.results)} props")

        # Generate summary
        summary = self._generate_summary(min_edge)

        # Print summary
        self._print_summary(summary)

        # Save results
        self._save_results(summary)

        return summary

    def _load_historical_props(
        self,
        start_date: date = None,
        end_date: date = None,
        stat_types: List[str] = None,
    ) -> List[Dict]:
        """Load historical props from database."""
        with self.db.Session() as session:
            from sqlalchemy import text

            # Build query
            query = """
                SELECT *
                FROM nhl_sgp_historical_odds
                WHERE 1=1
            """
            params = {}

            if start_date:
                query += " AND game_date >= :start_date"
                params['start_date'] = start_date
            if end_date:
                query += " AND game_date <= :end_date"
                params['end_date'] = end_date
            if stat_types:
                query += " AND stat_type = ANY(:stat_types)"
                params['stat_types'] = stat_types

            query += " ORDER BY game_date, player_name"

            result = session.execute(text(query), params)
            return [dict(row._mapping) for row in result]

    def _process_prop(self, prop: Dict) -> Optional[BacktestResult]:
        """Process a single prop and calculate edge."""
        try:
            # Build context (limited data in historical mode)
            ctx = PropContext(
                player_id=prop.get('player_id', 0),
                player_name=prop['player_name'],
                team=prop.get('away_team', '') or prop.get('home_team', ''),
                position='',  # Not available in historical
                stat_type=prop['stat_type'],
                line=float(prop['line']) if prop['line'] else 0.5,
                game_id=prop['event_id'],
                game_date=str(prop['game_date']),
                opponent='',
                is_home=False,
                # Most context fields unavailable in pure historical mode
                # This is a limitation - full backtest would need more data
            )

            # Calculate edge
            over_odds = prop['over_price'] or -110
            under_odds = prop['under_price'] or -110

            edge_result = self.calculator.calculate_edge(ctx, over_odds, under_odds)

            # Get actual outcome if settled
            actual_value = prop.get('actual_value')
            over_hit = prop.get('over_hit')

            # Determine if our prediction hit
            hit = None
            profit = None
            if over_hit is not None:
                if edge_result.direction == 'over':
                    hit = over_hit
                    odds = over_odds
                else:
                    hit = not over_hit
                    odds = under_odds

                # Calculate profit at $100 stake
                if hit:
                    if odds > 0:
                        profit = odds
                    else:
                        profit = 100 * 100 / abs(odds)
                else:
                    profit = -100

            return BacktestResult(
                prop_id=prop['id'],
                player_name=prop['player_name'],
                stat_type=prop['stat_type'],
                line=float(prop['line']) if prop['line'] else 0.5,
                direction=edge_result.direction,
                edge_pct=edge_result.edge_pct,
                confidence=edge_result.confidence,
                model_prob=edge_result.model_probability,
                market_prob=edge_result.market_probability,
                actual_value=actual_value,
                hit=hit,
                profit=profit,
            )

        except Exception as e:
            # Skip props with errors
            return None

    def _generate_summary(self, min_edge: float) -> BacktestSummary:
        """Generate summary statistics from results."""
        total = len(self.results)
        settled = [r for r in self.results if r.hit is not None]
        edge_props = [r for r in settled if abs(r.edge_pct) >= min_edge]

        # Overall metrics
        if edge_props:
            hits = sum(1 for r in edge_props if r.hit)
            overall_hit_rate = hits / len(edge_props)
            total_profit = sum(r.profit or 0 for r in edge_props)
            overall_roi = total_profit / (len(edge_props) * 100) * 100
        else:
            overall_hit_rate = 0
            overall_roi = 0

        # By edge bucket
        def bucket_stats(props):
            if not props:
                return {'hit_rate': 0, 'roi': 0, 'count': 0}
            hits = sum(1 for r in props if r.hit)
            profit = sum(r.profit or 0 for r in props)
            return {
                'hit_rate': hits / len(props) * 100,
                'roi': profit / (len(props) * 100) * 100,
                'count': len(props)
            }

        edge_5_10 = [r for r in settled if 5 <= abs(r.edge_pct) < 10]
        edge_10_15 = [r for r in settled if 10 <= abs(r.edge_pct) < 15]
        edge_15_plus = [r for r in settled if abs(r.edge_pct) >= 15]

        # By stat type
        by_stat = {}
        for stat_type in set(r.stat_type for r in settled):
            type_props = [r for r in settled if r.stat_type == stat_type and abs(r.edge_pct) >= min_edge]
            by_stat[stat_type] = bucket_stats(type_props)

        # By direction
        over_props = [r for r in edge_props if r.direction == 'over']
        under_props = [r for r in edge_props if r.direction == 'under']

        over_hit_rate = sum(1 for r in over_props if r.hit) / len(over_props) * 100 if over_props else 0
        under_hit_rate = sum(1 for r in under_props if r.hit) / len(under_props) * 100 if under_props else 0

        return BacktestSummary(
            total_props=total,
            settled_props=len(settled),
            edge_props=len(edge_props),
            overall_hit_rate=overall_hit_rate * 100,
            overall_roi=overall_roi,
            edge_5_10=bucket_stats(edge_5_10),
            edge_10_15=bucket_stats(edge_10_15),
            edge_15_plus=bucket_stats(edge_15_plus),
            by_stat_type=by_stat,
            over_hit_rate=over_hit_rate,
            under_hit_rate=under_hit_rate,
        )

    def _print_summary(self, summary: BacktestSummary):
        """Print summary to console."""
        print(f"\n{'='*60}")
        print("BACKTEST RESULTS")
        print(f"{'='*60}")

        print(f"\nTotal props: {summary.total_props}")
        print(f"Settled props: {summary.settled_props}")
        print(f"Props with edge >= 5%: {summary.edge_props}")

        print(f"\n--- Overall Performance (5%+ edge) ---")
        print(f"Hit rate: {summary.overall_hit_rate:.1f}%")
        print(f"ROI: {summary.overall_roi:.1f}%")
        print(f"Break-even needed: ~52.4% (at -110)")

        print(f"\n--- By Edge Bucket ---")
        for bucket_name, bucket in [
            ('5-10%', summary.edge_5_10),
            ('10-15%', summary.edge_10_15),
            ('15%+', summary.edge_15_plus)
        ]:
            if bucket['count'] > 0:
                print(f"  {bucket_name}: {bucket['hit_rate']:.1f}% hit rate, {bucket['roi']:.1f}% ROI ({bucket['count']} props)")

        print(f"\n--- By Stat Type ---")
        for stat, stats in summary.by_stat_type.items():
            if stats['count'] > 0:
                print(f"  {stat}: {stats['hit_rate']:.1f}% hit rate, {stats['roi']:.1f}% ROI ({stats['count']} props)")

        print(f"\n--- By Direction ---")
        print(f"  OVER: {summary.over_hit_rate:.1f}%")
        print(f"  UNDER: {summary.under_hit_rate:.1f}%")

        # Verdict
        print(f"\n{'='*60}")
        print("VERDICT")
        print(f"{'='*60}")

        if summary.overall_hit_rate >= 54:
            print("PROFITABLE - Edge detection shows positive signal")
            print("Recommendation: Proceed with SGP engine development")
        elif summary.overall_hit_rate >= 50:
            print("MARGINAL - Edge detection at break-even")
            print("Recommendation: Need more data or signal refinement")
        else:
            print("UNPROFITABLE - Edge detection below break-even")
            print("Recommendation: Review signals or increase data quality")

    def _save_results(self, summary: BacktestSummary):
        """Save results to file."""
        output_file = DATA_DIR / "backtest_results.json"

        output = {
            'generated_at': datetime.now().isoformat(),
            'summary': asdict(summary),
            'results_sample': [asdict(r) for r in self.results[:100]],
        }

        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        print(f"\nResults saved to: {output_file}")


def main():
    """Run backtest from command line."""
    import argparse

    parser = argparse.ArgumentParser(description='Run NHL SGP backtest')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--min-edge', type=float, default=5.0, help='Minimum edge %')
    parser.add_argument('--stat-types', nargs='+', help='Filter stat types')

    args = parser.parse_args()

    engine = BacktestEngine()
    engine.run_backtest(
        start_date=args.start,
        end_date=args.end,
        min_edge=args.min_edge,
        stat_types=args.stat_types,
    )


if __name__ == "__main__":
    main()
