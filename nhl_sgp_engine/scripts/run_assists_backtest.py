#!/usr/bin/env python3
"""
Assists-Only Backtest

Evaluate performance of assists props with pipeline context.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import datetime
from collections import defaultdict
from sqlalchemy import text

from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.settings import DATA_DIR


def run_assists_backtest(min_edge: float = 5.0):
    """Run backtest on assists props only."""
    print(f"\n{'='*70}")
    print("ASSISTS-ONLY BACKTEST")
    print(f"{'='*70}")
    print(f"Min edge: {min_edge}%")
    print(f"{'='*70}\n")

    sgp_db = NHLSGPDBManager()
    pipeline = PipelineAdapter()
    calculator = EdgeCalculator()

    # Load assists historical odds
    with sgp_db.Session() as session:
        result = session.execute(text('''
            SELECT DISTINCT ON (player_name, game_date, line)
                event_id, game_date, home_team, away_team,
                player_name, stat_type, market_key, line,
                over_price, under_price, bookmaker
            FROM nhl_sgp_historical_odds
            WHERE market_key = 'player_assists'
            ORDER BY player_name, game_date, line, bookmaker
        '''))
        odds_data = [dict(row._mapping) for row in result]

    print(f"Loaded {len(odds_data)} unique assists props")

    # Process each prop
    results = []
    stats = {
        'total': 0,
        'with_context': 0,
        'settled': 0,
        'with_edge': 0,
    }

    by_edge_bucket = defaultdict(lambda: {'total': 0, 'hits': 0, 'roi': 0})
    by_scoreable = defaultdict(lambda: {'total': 0, 'hits': 0})
    by_rank = defaultdict(lambda: {'total': 0, 'hits': 0})

    for odds in odds_data:
        stats['total'] += 1
        player_name = odds['player_name']
        game_date = odds['game_date']
        line = float(odds['line'])

        # Get pipeline context
        ctx = pipeline.enrich_prop_context(
            player_name=player_name,
            stat_type='assists',  # Use assists stat type
            line=line,
            game_date=game_date,
            event_id=odds['event_id'],
        )

        if ctx.pipeline_score is None:
            continue

        stats['with_context'] += 1

        # Get actual outcome (assists from pipeline)
        actual = pipeline.get_actual_outcome(player_name, 'assists', game_date)

        if actual is None:
            continue

        stats['settled'] += 1

        # Calculate edge
        over_odds = odds['over_price'] or -110
        under_odds = odds['under_price'] or -110

        edge_result = calculator.calculate_edge(ctx, over_odds, under_odds)

        if edge_result.edge_pct < min_edge:
            continue

        stats['with_edge'] += 1

        # Determine hit
        if edge_result.direction == 'over':
            hit = actual > line
        else:
            hit = actual <= line

        # Track by edge bucket
        edge_bucket = f"{int(edge_result.edge_pct // 3) * 3}-{int(edge_result.edge_pct // 3) * 3 + 3}%"
        by_edge_bucket[edge_bucket]['total'] += 1
        if hit:
            by_edge_bucket[edge_bucket]['hits'] += 1
            by_edge_bucket[edge_bucket]['roi'] += 100 / abs(over_odds if over_odds > 0 else over_odds)
        else:
            by_edge_bucket[edge_bucket]['roi'] -= 1

        # Track by scoreable
        pred_ctx = pipeline.get_prediction_context(player_name, game_date)
        is_scoreable = pred_ctx.get('is_scoreable', False) if pred_ctx else False
        scoreable_key = 'scoreable' if is_scoreable else 'non_scoreable'
        by_scoreable[scoreable_key]['total'] += 1
        if hit:
            by_scoreable[scoreable_key]['hits'] += 1

        # Track by rank
        rank = ctx.pipeline_rank or 999
        if rank <= 10:
            rank_key = 'top_10'
        elif rank <= 25:
            rank_key = '11-25'
        elif rank <= 50:
            rank_key = '26-50'
        else:
            rank_key = '51+'

        by_rank[rank_key]['total'] += 1
        if hit:
            by_rank[rank_key]['hits'] += 1

        results.append({
            'player': player_name,
            'date': str(game_date),
            'line': line,
            'direction': edge_result.direction,
            'edge': edge_result.edge_pct,
            'actual': actual,
            'hit': hit,
            'rank': rank,
            'scoreable': is_scoreable,
        })

    # Print results
    print(f"\n{'='*70}")
    print("ASSISTS BACKTEST RESULTS")
    print(f"{'='*70}\n")

    print(f"Total assists props: {stats['total']:,}")
    print(f"With pipeline context: {stats['with_context']:,} ({100*stats['with_context']/stats['total']:.1f}%)")
    print(f"Settled: {stats['settled']:,}")
    print(f"With {min_edge}%+ edge: {stats['with_edge']:,}")

    if stats['with_edge'] > 0:
        hits = sum(1 for r in results if r['hit'])
        hit_rate = 100 * hits / len(results)
        print(f"\n--- Overall Performance ({min_edge}%+ edge) ---")
        print(f"Hit rate: {hit_rate:.1f}% ({hits}/{len(results)})")
        print(f"Break-even needed: ~52.4%")
        print(f"Status: {'ABOVE' if hit_rate > 52.4 else 'BELOW'} BREAK-EVEN")

        print(f"\n--- By Edge Bucket ---")
        for bucket in sorted(by_edge_bucket.keys()):
            data = by_edge_bucket[bucket]
            if data['total'] > 0:
                rate = 100 * data['hits'] / data['total']
                print(f"{bucket:>10}: {rate:.1f}% hit ({data['hits']}/{data['total']})")

        print(f"\n--- By Scoreable Status ---")
        for status in ['scoreable', 'non_scoreable']:
            data = by_scoreable[status]
            if data['total'] > 0:
                rate = 100 * data['hits'] / data['total']
                print(f"{status:>15}: {rate:.1f}% hit ({data['hits']}/{data['total']})")

        print(f"\n--- By Pipeline Rank ---")
        for rank_key in ['top_10', '11-25', '26-50', '51+']:
            data = by_rank[rank_key]
            if data['total'] > 0:
                rate = 100 * data['hits'] / data['total']
                print(f"{rank_key:>10}: {rate:.1f}% hit ({data['hits']}/{data['total']})")

    # Save results
    output = {
        'run_date': datetime.now().isoformat(),
        'stat_type': 'assists',
        'min_edge': min_edge,
        'stats': stats,
        'by_edge_bucket': {k: dict(v) for k, v in by_edge_bucket.items()},
        'by_scoreable': {k: dict(v) for k, v in by_scoreable.items()},
        'by_rank': {k: dict(v) for k, v in by_rank.items()},
        'results': results[:100],  # Sample
    }

    output_file = DATA_DIR / 'assists_backtest_results.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"Results saved to: {output_file}")
    print(f"{'='*70}")

    return results


if __name__ == "__main__":
    run_assists_backtest(min_edge=5.0)
