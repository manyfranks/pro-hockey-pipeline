#!/usr/bin/env python3
"""
Points-Only Backtest

Based on LEARNINGS.md findings:
- Points props: 50% hit rate (promising)
- Goals props: 7.4% hit rate (abandon)

This script filters to points props only to validate
the true performance of our edge detection.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.settings import MIN_EDGE_PCT, DATA_DIR


@dataclass
class PointsResult:
    """Result for a points prop with full context."""
    player_name: str
    line: float
    direction: str
    edge_pct: float
    confidence: float

    # Pipeline context
    pipeline_score: Optional[float]
    pipeline_rank: Optional[int]
    line_number: Optional[int]
    pp_unit: Optional[int]
    is_scoreable: bool
    recent_ppg: Optional[float]
    season_ppg: Optional[float]

    # Outcome
    actual_value: Optional[float]
    hit: Optional[bool]
    profit: Optional[float]

    # Context quality
    has_pipeline_context: bool


def run_points_only_backtest(
    start_date: str = None,
    end_date: str = None,
    min_edge: float = MIN_EDGE_PCT,
):
    """
    Run backtest filtered to points props only.

    Args:
        start_date: Start date (YYYY-MM-DD), defaults to earliest with data
        end_date: End date (YYYY-MM-DD), defaults to latest with data
        min_edge: Minimum edge % to consider
    """
    print(f"\n{'='*70}")
    print("NHL SGP ENGINE - POINTS-ONLY BACKTEST")
    print(f"{'='*70}")
    print(f"Stat type: points ONLY (excluding goals)")
    print(f"Min edge: {min_edge}%")
    print(f"{'='*70}\n")

    # Initialize components
    pipeline = PipelineAdapter()
    sgp_db = NHLSGPDBManager()
    calculator = EdgeCalculator()

    # Get all historical odds
    with sgp_db.Session() as session:
        from sqlalchemy import text
        result = session.execute(text("""
            SELECT DISTINCT game_date
            FROM nhl_sgp_historical_odds
            WHERE stat_type = 'points'
            ORDER BY game_date
        """))
        dates_with_data = [row.game_date for row in result]

    if not dates_with_data:
        print("No points prop data found in historical odds!")
        return

    print(f"Found points data for {len(dates_with_data)} dates:")
    for d in dates_with_data:
        print(f"  - {d}")

    results: List[PointsResult] = []

    for game_date in dates_with_data:
        date_str = game_date.strftime("%Y-%m-%d")
        print(f"\n--- Processing {date_str} ---")

        # Get points props only
        with sgp_db.Session() as session:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT * FROM nhl_sgp_historical_odds
                WHERE game_date = :game_date
                  AND stat_type = 'points'
            """), {'game_date': game_date})
            props_data = [dict(row._mapping) for row in result]

        print(f"  Found {len(props_data)} points props")

        # Get pipeline predictions for this date
        predictions = pipeline.get_predictions_for_date(game_date)
        print(f"  Found {len(predictions)} pipeline predictions")

        # Process each prop
        for prop in props_data:
            player_name = prop.get('player_name', '')
            line = float(prop.get('line', 0.5))

            # Enrich with pipeline context
            ctx = pipeline.enrich_prop_context(
                player_name=player_name,
                stat_type='points',
                line=line,
                game_date=game_date,
                event_id=prop.get('event_id', ''),
            )

            has_context = ctx.pipeline_score is not None

            # Calculate edge
            over_odds = prop.get('over_price') or -110
            under_odds = prop.get('under_price') or -110

            edge_result = calculator.calculate_edge(ctx, over_odds, under_odds)

            # Get actual outcome
            actual = pipeline.get_actual_outcome(player_name, 'points', game_date)

            # Determine hit
            hit = None
            profit = None
            if actual is not None:
                if edge_result.direction == 'over':
                    hit = actual > line
                    odds = over_odds
                else:
                    hit = actual <= line
                    odds = under_odds

                if hit:
                    profit = odds if odds > 0 else (100 * 100 / abs(odds))
                else:
                    profit = -100

            # Get scoreable status
            pred_ctx = pipeline.get_prediction_context(player_name, game_date)
            is_scoreable = pred_ctx.get('is_scoreable', False) if pred_ctx else False

            # Calculate season PPG
            season_ppg = None
            if ctx.season_games and ctx.season_points:
                season_ppg = float(ctx.season_points) / float(ctx.season_games)

            results.append(PointsResult(
                player_name=player_name,
                line=line,
                direction=edge_result.direction,
                edge_pct=edge_result.edge_pct,
                confidence=edge_result.confidence,
                pipeline_score=ctx.pipeline_score,
                pipeline_rank=ctx.pipeline_rank,
                line_number=ctx.line_number,
                pp_unit=ctx.pp_unit,
                is_scoreable=is_scoreable,
                recent_ppg=float(ctx.recent_ppg) if ctx.recent_ppg else None,
                season_ppg=season_ppg,
                actual_value=actual,
                hit=hit,
                profit=profit,
                has_pipeline_context=has_context,
            ))

    # Generate report
    generate_points_report(results, min_edge)


def generate_points_report(results: List[PointsResult], min_edge: float):
    """Generate performance report for points props."""
    print(f"\n{'='*70}")
    print("POINTS-ONLY BACKTEST RESULTS")
    print(f"{'='*70}")

    total = len(results)
    with_context = [r for r in results if r.has_pipeline_context]
    settled = [r for r in results if r.hit is not None]
    edge_props = [r for r in settled if abs(r.edge_pct) >= min_edge]

    print(f"\nTotal points props: {total}")
    print(f"With pipeline context: {len(with_context)} ({len(with_context)/total*100:.0f}%)")
    print(f"Settled: {len(settled)}")
    print(f"With {min_edge}%+ edge: {len(edge_props)}")

    if not edge_props:
        print("\nNo settled props with sufficient edge.")
        return

    # Overall performance
    hits = sum(1 for r in edge_props if r.hit)
    hit_rate = hits / len(edge_props) * 100
    total_profit = sum(r.profit or 0 for r in edge_props)
    roi = total_profit / (len(edge_props) * 100) * 100

    print(f"\n--- OVERALL PERFORMANCE ({min_edge}%+ edge) ---")
    print(f"Hit rate: {hit_rate:.1f}% ({hits}/{len(edge_props)})")
    print(f"ROI: {roi:.1f}%")
    print(f"Break-even needed: ~52.4%")

    # By edge bucket
    print(f"\n--- BY EDGE BUCKET ---")
    for low, high, label in [(5, 8, "5-8%"), (8, 12, "8-12%"), (12, 15, "12-15%"), (15, 100, "15%+")]:
        bucket = [r for r in edge_props if low <= abs(r.edge_pct) < high]
        if bucket:
            b_hits = sum(1 for r in bucket if r.hit)
            b_rate = b_hits / len(bucket) * 100
            b_profit = sum(r.profit or 0 for r in bucket)
            b_roi = b_profit / (len(bucket) * 100) * 100
            print(f"  {label}: {b_rate:.1f}% hit, {b_roi:.1f}% ROI ({len(bucket)} props)")

    # By direction
    print(f"\n--- BY DIRECTION ---")
    for direction in ['over', 'under']:
        dir_props = [r for r in edge_props if r.direction == direction]
        if dir_props:
            d_hits = sum(1 for r in dir_props if r.hit)
            d_rate = d_hits / len(dir_props) * 100
            print(f"  {direction.upper()}: {d_rate:.1f}% ({d_hits}/{len(dir_props)})")

    # By pipeline context
    print(f"\n--- BY PIPELINE CONTEXT ---")
    with_ctx = [r for r in edge_props if r.has_pipeline_context]
    without_ctx = [r for r in edge_props if not r.has_pipeline_context]

    if with_ctx:
        ctx_hits = sum(1 for r in with_ctx if r.hit)
        ctx_rate = ctx_hits / len(with_ctx) * 100
        print(f"  With context: {ctx_rate:.1f}% ({ctx_hits}/{len(with_ctx)})")

    if without_ctx:
        no_ctx_hits = sum(1 for r in without_ctx if r.hit)
        no_ctx_rate = no_ctx_hits / len(without_ctx) * 100
        print(f"  Without context: {no_ctx_rate:.1f}% ({no_ctx_hits}/{len(without_ctx)})")

    # By scoreable status
    print(f"\n--- BY SCOREABLE STATUS ---")
    scoreable = [r for r in edge_props if r.is_scoreable]
    non_scoreable = [r for r in edge_props if not r.is_scoreable]

    if scoreable:
        s_hits = sum(1 for r in scoreable if r.hit)
        s_rate = s_hits / len(scoreable) * 100
        print(f"  Scoreable: {s_rate:.1f}% ({s_hits}/{len(scoreable)})")

    if non_scoreable:
        ns_hits = sum(1 for r in non_scoreable if r.hit)
        ns_rate = ns_hits / len(non_scoreable) * 100
        print(f"  Non-scoreable: {ns_rate:.1f}% ({ns_hits}/{len(non_scoreable)})")

    # By line
    print(f"\n--- BY LINE VALUE ---")
    for line_val in [0.5, 1.5, 2.5]:
        line_props = [r for r in edge_props if r.line == line_val]
        if line_props:
            l_hits = sum(1 for r in line_props if r.hit)
            l_rate = l_hits / len(line_props) * 100
            print(f"  {line_val} line: {l_rate:.1f}% ({l_hits}/{len(line_props)})")

    # By pipeline rank
    print(f"\n--- BY PIPELINE RANK ---")
    ranked = [r for r in edge_props if r.pipeline_rank is not None]
    for low, high, label in [(1, 10, "Top 10"), (11, 25, "11-25"), (26, 50, "26-50"), (51, 200, "51+")]:
        bucket = [r for r in ranked if low <= r.pipeline_rank <= high]
        if bucket:
            b_hits = sum(1 for r in bucket if r.hit)
            b_rate = b_hits / len(bucket) * 100
            print(f"  Rank {label}: {b_rate:.1f}% ({b_hits}/{len(bucket)})")

    # Top performers
    print(f"\n--- TOP INDIVIDUAL PROPS ---")
    sorted_by_edge = sorted(edge_props, key=lambda x: abs(x.edge_pct), reverse=True)
    for r in sorted_by_edge[:10]:
        status = "HIT" if r.hit else "MISS"
        ctx = "CTX" if r.has_pipeline_context else "---"
        print(f"  {r.player_name[:20]:<20} | {r.direction.upper():>5} {r.line} | {r.edge_pct:>5.1f}% | {status} | {ctx}")

    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print(f"{'='*70}")

    if hit_rate >= 54:
        print("PROFITABLE - Signal validated!")
        print("Recommendation: Proceed with production build for POINTS props")
    elif hit_rate >= 52:
        print("MARGINAL - At break-even")
        print("Recommendation: Expand sample size before production")
    elif hit_rate >= 48:
        print("NEAR BREAK-EVEN - Potential with refinement")
        print("Recommendation: Adjust signal weights and re-test")
    else:
        print("BELOW BREAK-EVEN")
        print("Recommendation: Review signal methodology")

    # Save results
    output_file = DATA_DIR / "points_only_backtest.json"
    with open(output_file, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'stat_type': 'points_only',
            'total_props': total,
            'settled_props': len(settled),
            'edge_props': len(edge_props),
            'hit_rate': hit_rate,
            'roi': roi,
            'results': [asdict(r) for r in results],
        }, f, indent=2, default=str)

    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Run points-only NHL SGP backtest')
    parser.add_argument('--min-edge', type=float, default=5.0, help='Min edge %')

    args = parser.parse_args()

    run_points_only_backtest(min_edge=args.min_edge)
