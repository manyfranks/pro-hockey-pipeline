#!/usr/bin/env python3
"""
Parlay Settlement Script

Settles parlays by fetching actual outcomes from the pipeline.
Run after games complete to update leg results and parlay settlements.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from sqlalchemy import text

from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter


def calculate_profit(combined_odds: int, stake: float = 100.0) -> float:
    """Calculate profit from American odds at given stake."""
    if combined_odds > 0:
        return stake * (combined_odds / 100)
    else:
        return stake * (100 / abs(combined_odds))


def settle_leg(
    leg: Dict,
    game_date: date,
    pipeline: PipelineAdapter,
) -> Tuple[Optional[float], str]:
    """
    Settle a single leg.

    Returns:
        Tuple of (actual_value, result)
        result is one of: 'WIN', 'LOSS', 'PUSH', 'VOID'
    """
    player_name = leg['player_name']
    stat_type = leg['stat_type']
    line = float(leg['line'])
    direction = leg['direction']

    # Get actual outcome from pipeline
    actual = pipeline.get_actual_outcome(player_name, stat_type, game_date)

    if actual is None:
        return None, 'VOID'

    # Determine result
    if actual == line:
        result = 'PUSH'
    elif direction == 'over':
        result = 'WIN' if actual > line else 'LOSS'
    else:  # under
        result = 'WIN' if actual < line else 'LOSS'

    return float(actual), result


def settle_parlays_for_date(
    game_date: date = None,
    dry_run: bool = False,
):
    """
    Settle all parlays for a specific date.

    Args:
        game_date: Date to settle (default: yesterday)
        dry_run: If True, don't update database
    """
    game_date = game_date or (date.today() - timedelta(days=1))
    date_str = game_date.strftime('%Y-%m-%d')

    print(f"\n{'='*70}")
    print("NHL SGP ENGINE - PARLAY SETTLEMENT")
    print(f"{'='*70}")
    print(f"Date: {date_str}")
    print(f"Dry run: {dry_run}")
    print(f"{'='*70}\n")

    sgp_db = NHLSGPDBManager()
    pipeline = PipelineAdapter()

    # Get parlays for date
    parlays = sgp_db.get_parlays_by_date(game_date)

    if not parlays:
        print(f"No parlays found for {date_str}")
        return

    print(f"Found {len(parlays)} parlays to settle\n")

    settlements = []
    leg_updates = []

    for parlay in parlays:
        parlay_id = str(parlay['id'])
        home_team = parlay['home_team']
        away_team = parlay['away_team']
        combined_odds = parlay['combined_odds']
        legs = parlay.get('legs', [])

        print(f"\n--- {away_team} @ {home_team} ---")
        print(f"Parlay ID: {parlay_id[:8]}...")
        print(f"Combined odds: +{combined_odds}" if combined_odds > 0 else f"Combined odds: {combined_odds}")

        if not legs:
            print("  No legs found!")
            continue

        # Settle each leg
        legs_hit = 0
        legs_voided = 0
        legs_pushed = 0
        leg_results = []

        for leg in legs:
            if leg is None:
                continue

            actual, result = settle_leg(leg, game_date, pipeline)

            leg_results.append({
                'leg_number': leg.get('leg_number'),
                'player_name': leg.get('player_name'),
                'stat_type': leg.get('stat_type'),
                'line': leg.get('line'),
                'direction': leg.get('direction'),
                'actual': actual,
                'result': result,
            })

            # Count results
            if result == 'WIN':
                legs_hit += 1
            elif result == 'VOID':
                legs_voided += 1
            elif result == 'PUSH':
                legs_pushed += 1

            # Print leg result
            status_icon = '✓' if result == 'WIN' else '✗' if result == 'LOSS' else '–'
            actual_str = f"{actual:.0f}" if actual is not None else "N/A"
            print(f"  {status_icon} {leg.get('player_name')} {leg.get('stat_type')} "
                  f"{leg.get('direction').upper()} {leg.get('line')} | "
                  f"Actual: {actual_str} | {result}")

            # Prepare leg update
            leg_updates.append({
                'parlay_id': parlay_id,
                'player_name': leg.get('player_name'),
                'stat_type': leg.get('stat_type'),
                'actual_value': actual,
                'result': result,
            })

        # Determine parlay result
        total_scoreable = len(legs) - legs_voided
        legs_needed = total_scoreable - legs_pushed  # Pushes reduce legs needed

        if legs_voided == len(legs):
            parlay_result = 'VOID'
            profit = 0
        elif legs_hit == legs_needed:
            parlay_result = 'WIN'
            profit = calculate_profit(combined_odds)
        else:
            parlay_result = 'LOSS'
            profit = -100  # Assuming $100 stake

        print(f"\n  PARLAY RESULT: {parlay_result}")
        print(f"  Legs: {legs_hit}/{total_scoreable} hit")
        print(f"  Profit: ${profit:+.2f}")

        # Prepare settlement record
        settlements.append({
            'id': uuid.uuid4(),
            'parlay_id': parlay_id,
            'legs_hit': legs_hit,
            'total_legs': total_scoreable,
            'result': parlay_result,
            'profit': profit,
            'settled_at': datetime.utcnow(),
            'notes': f"Auto-settled from pipeline data",
        })

    # Summary
    print(f"\n{'='*70}")
    print("SETTLEMENT SUMMARY")
    print(f"{'='*70}")

    total_profit = sum(s['profit'] for s in settlements)
    wins = sum(1 for s in settlements if s['result'] == 'WIN')
    losses = sum(1 for s in settlements if s['result'] == 'LOSS')
    voids = sum(1 for s in settlements if s['result'] == 'VOID')

    print(f"Parlays settled: {len(settlements)}")
    print(f"Wins: {wins} | Losses: {losses} | Voids: {voids}")
    print(f"Total profit: ${total_profit:+.2f}")
    print(f"ROI: {(total_profit / (len(settlements) * 100)) * 100:.1f}%" if settlements else "N/A")

    # Save to database
    if not dry_run and settlements:
        print(f"\n--- Saving to Database ---")
        try:
            with sgp_db.Session() as session:
                # Update legs
                for leg_update in leg_updates:
                    session.execute(text("""
                        UPDATE nhl_sgp_legs
                        SET actual_value = :actual_value, result = :result
                        WHERE parlay_id = :parlay_id::uuid
                          AND player_name = :player_name
                          AND stat_type = :stat_type
                    """), leg_update)

                # Insert settlements
                for settlement in settlements:
                    session.execute(text("""
                        INSERT INTO nhl_sgp_settlements
                        (id, parlay_id, legs_hit, total_legs, result, profit, settled_at, notes)
                        VALUES (:id, :parlay_id::uuid, :legs_hit, :total_legs, :result, :profit, :settled_at, :notes)
                        ON CONFLICT DO NOTHING
                    """), settlement)

                session.commit()
                print(f"  Updated {len(leg_updates)} legs")
                print(f"  Created {len(settlements)} settlement records")

        except Exception as e:
            print(f"  Error saving: {e}")

    print(f"\n{'='*70}")
    print("COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Settle NHL SGP parlays')
    parser.add_argument('--date', help='Date to settle (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to database')

    args = parser.parse_args()

    game_date = None
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    settle_parlays_for_date(
        game_date=game_date,
        dry_run=args.dry_run,
    )
