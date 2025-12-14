#!/usr/bin/env python3
"""
Run Enriched Backtest with Pipeline Context

This script:
1. Loads historical odds from Odds API (or cached data)
2. Enriches each prop with NHL pipeline prediction context
3. Calculates edges with full signal context
4. Compares to actual outcomes from pipeline settlements
5. Generates performance report
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.settings import MIN_EDGE_PCT, DATA_DIR
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS


@dataclass
class EnrichedResult:
    """Result for a prop with pipeline context."""
    player_name: str
    stat_type: str
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

    # Outcome
    actual_value: Optional[float]
    hit: Optional[bool]
    profit: Optional[float]

    # Context quality
    has_pipeline_context: bool


def run_enriched_backtest(
    start_date: str,
    end_date: str,
    max_games: int = 50,
    use_cached_odds: bool = True,
    fetch_new_odds: bool = False,
    min_edge: float = MIN_EDGE_PCT,
):
    """
    Run backtest with enriched pipeline context.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        max_games: Max games to fetch odds for (API budget)
        use_cached_odds: Use cached odds data if available
        fetch_new_odds: Fetch new odds from API
        min_edge: Minimum edge % to consider
    """
    print(f"\n{'='*70}")
    print("NHL SGP ENGINE - ENRICHED BACKTEST")
    print(f"{'='*70}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Max games: {max_games}")
    print(f"Min edge: {min_edge}%")
    print(f"{'='*70}\n")

    # Initialize components
    odds_client = OddsAPIClient()
    pipeline = PipelineAdapter()
    sgp_db = NHLSGPDBManager()
    calculator = EdgeCalculator()

    # Get dates with settled predictions
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    results: List[EnrichedResult] = []
    games_processed = 0

    current_date = start
    while current_date <= end and games_processed < max_games:
        date_str = current_date.strftime("%Y-%m-%d")
        print(f"\n--- Processing {date_str} ---")

        # Get pipeline predictions for this date
        predictions = pipeline.get_predictions_for_date(current_date)
        if not predictions:
            print(f"  No pipeline predictions for {date_str}")
            current_date += timedelta(days=1)
            continue

        print(f"  Found {len(predictions)} pipeline predictions")

        # Check for cached odds (get ALL odds, not just unsettled)
        with sgp_db.Session() as session:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT * FROM nhl_sgp_historical_odds
                WHERE game_date = :game_date
            """), {'game_date': current_date})
            cached_odds = [dict(row._mapping) for row in result]

        if cached_odds:
            print(f"  Using {len(cached_odds)} cached odds")
            props_data = cached_odds
        elif fetch_new_odds:
            # Fetch historical odds from API
            print(f"  Fetching odds from API...")
            try:
                events = odds_client.get_historical_events(date_str)
                print(f"  Found {len(events)} events")

                props_data = []
                for event in events[:3]:  # Limit per day for budget
                    event_id = event.get('id')
                    odds_data = odds_client.get_historical_event_odds(
                        event_id=event_id,
                        date_str=date_str,
                        markets=BACKTEST_MARKETS,
                    )

                    # Parse props
                    props = odds_client.parse_player_props(
                        odds_data.get('data', odds_data),
                        market_keys=BACKTEST_MARKETS,
                    )

                    for prop in props:
                        props_data.append({
                            'event_id': event_id,
                            'game_date': current_date,
                            'player_name': prop.player_name,
                            'stat_type': prop.stat_type,
                            'line': prop.line,
                            'over_price': prop.over_price,
                            'under_price': prop.under_price,
                            'bookmaker': prop.bookmaker,
                        })

                    games_processed += 1

                print(f"  Fetched {len(props_data)} props")

            except Exception as e:
                print(f"  Error fetching odds: {e}")
                current_date += timedelta(days=1)
                continue
        else:
            print(f"  No cached odds and fetch_new_odds=False, skipping")
            current_date += timedelta(days=1)
            continue

        # Process each prop
        for prop in props_data:
            player_name = prop.get('player_name', '')
            stat_type = prop.get('stat_type', '')
            line = float(prop.get('line', 0.5))

            # Enrich with pipeline context
            ctx = pipeline.enrich_prop_context(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                game_date=current_date,
                event_id=prop.get('event_id', ''),
            )

            has_context = ctx.pipeline_score is not None

            # Calculate edge
            over_odds = prop.get('over_price') or -110
            under_odds = prop.get('under_price') or -110

            edge_result = calculator.calculate_edge(ctx, over_odds, under_odds)

            # Get actual outcome from pipeline
            actual = pipeline.get_actual_outcome(player_name, stat_type, current_date)

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

            # Check if this was a "scoreable" prediction
            pred_ctx = pipeline.get_prediction_context(player_name, current_date)
            is_scoreable = pred_ctx.get('is_scoreable', False) if pred_ctx else False

            results.append(EnrichedResult(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                direction=edge_result.direction,
                edge_pct=edge_result.edge_pct,
                confidence=edge_result.confidence,
                pipeline_score=ctx.pipeline_score,
                pipeline_rank=ctx.pipeline_rank,
                line_number=ctx.line_number,
                pp_unit=ctx.pp_unit,
                is_scoreable=is_scoreable,
                actual_value=actual,
                hit=hit,
                profit=profit,
                has_pipeline_context=has_context,
            ))

        current_date += timedelta(days=1)

    # Generate report
    generate_report(results, min_edge)


def generate_report(results: List[EnrichedResult], min_edge: float):
    """Generate performance report."""
    print(f"\n{'='*70}")
    print("BACKTEST RESULTS")
    print(f"{'='*70}")

    total = len(results)
    with_context = [r for r in results if r.has_pipeline_context]
    settled = [r for r in results if r.hit is not None]
    edge_props = [r for r in settled if abs(r.edge_pct) >= min_edge]

    print(f"\nTotal props processed: {total}")
    print(f"Props with pipeline context: {len(with_context)} ({len(with_context)/total*100:.0f}%)")
    print(f"Settled props: {len(settled)}")
    print(f"Props with {min_edge}%+ edge: {len(edge_props)}")

    if not edge_props:
        print("\nNo settled props with sufficient edge to analyze.")
        return

    # Overall performance
    hits = sum(1 for r in edge_props if r.hit)
    hit_rate = hits / len(edge_props) * 100
    total_profit = sum(r.profit or 0 for r in edge_props)
    roi = total_profit / (len(edge_props) * 100) * 100

    print(f"\n--- Overall Performance ({min_edge}%+ edge) ---")
    print(f"Hit rate: {hit_rate:.1f}% ({hits}/{len(edge_props)})")
    print(f"ROI: {roi:.1f}%")
    print(f"Break-even needed: ~52.4%")

    # With vs without pipeline context
    with_ctx_edge = [r for r in edge_props if r.has_pipeline_context]
    without_ctx_edge = [r for r in edge_props if not r.has_pipeline_context]

    if with_ctx_edge:
        ctx_hits = sum(1 for r in with_ctx_edge if r.hit)
        ctx_rate = ctx_hits / len(with_ctx_edge) * 100
        print(f"\n--- With Pipeline Context ---")
        print(f"Hit rate: {ctx_rate:.1f}% ({ctx_hits}/{len(with_ctx_edge)})")

    if without_ctx_edge:
        no_ctx_hits = sum(1 for r in without_ctx_edge if r.hit)
        no_ctx_rate = no_ctx_hits / len(without_ctx_edge) * 100
        print(f"\n--- Without Pipeline Context ---")
        print(f"Hit rate: {no_ctx_rate:.1f}% ({no_ctx_hits}/{len(without_ctx_edge)})")

    # By scoreable status
    scoreable = [r for r in edge_props if r.is_scoreable]
    non_scoreable = [r for r in edge_props if not r.is_scoreable]

    if scoreable:
        score_hits = sum(1 for r in scoreable if r.hit)
        score_rate = score_hits / len(scoreable) * 100
        print(f"\n--- Scoreable Players Only ---")
        print(f"Hit rate: {score_rate:.1f}% ({score_hits}/{len(scoreable)})")

    # By edge bucket
    print(f"\n--- By Edge Bucket ---")
    for low, high, label in [(5, 10, "5-10%"), (10, 15, "10-15%"), (15, 100, "15%+")]:
        bucket = [r for r in edge_props if low <= abs(r.edge_pct) < high]
        if bucket:
            b_hits = sum(1 for r in bucket if r.hit)
            b_rate = b_hits / len(bucket) * 100
            b_profit = sum(r.profit or 0 for r in bucket)
            b_roi = b_profit / (len(bucket) * 100) * 100
            print(f"  {label}: {b_rate:.1f}% hit, {b_roi:.1f}% ROI ({len(bucket)} props)")

    # By stat type
    print(f"\n--- By Stat Type ---")
    by_stat = defaultdict(list)
    for r in edge_props:
        by_stat[r.stat_type].append(r)

    for stat, props in sorted(by_stat.items()):
        s_hits = sum(1 for r in props if r.hit)
        s_rate = s_hits / len(props) * 100
        print(f"  {stat}: {s_rate:.1f}% ({s_hits}/{len(props)})")

    # By pipeline rank
    print(f"\n--- By Pipeline Rank ---")
    ranked = [r for r in edge_props if r.pipeline_rank is not None]
    for low, high, label in [(1, 10, "Top 10"), (11, 25, "11-25"), (26, 100, "26+")]:
        bucket = [r for r in ranked if low <= r.pipeline_rank <= high]
        if bucket:
            b_hits = sum(1 for r in bucket if r.hit)
            b_rate = b_hits / len(bucket) * 100
            print(f"  Rank {label}: {b_rate:.1f}% ({b_hits}/{len(bucket)})")

    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print(f"{'='*70}")

    if hit_rate >= 54:
        print("PROFITABLE - Signal detected!")
        print("Recommendation: Proceed with NHL SGP engine production build")
    elif hit_rate >= 50:
        print("MARGINAL - Near break-even")
        print("Recommendation: Refine signals or increase sample size")
    else:
        print("BELOW BREAK-EVEN")
        print("Recommendation: Review signal methodology")

    # Save results
    output_file = DATA_DIR / "enriched_backtest_results.json"
    with open(output_file, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'total_props': total,
            'settled_props': len(settled),
            'edge_props': len(edge_props),
            'hit_rate': hit_rate,
            'roi': roi,
            'sample_results': [asdict(r) for r in results[:200]],
        }, f, indent=2, default=str)

    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Run enriched NHL SGP backtest')
    parser.add_argument('--start', default='2025-11-15', help='Start date')
    parser.add_argument('--end', default='2025-12-01', help='End date')
    parser.add_argument('--max-games', type=int, default=50, help='Max games to fetch')
    parser.add_argument('--fetch-odds', action='store_true', help='Fetch new odds from API')
    parser.add_argument('--min-edge', type=float, default=5.0, help='Min edge %')

    args = parser.parse_args()

    run_enriched_backtest(
        start_date=args.start,
        end_date=args.end,
        max_games=args.max_games,
        fetch_new_odds=args.fetch_odds,
        min_edge=args.min_edge,
    )
