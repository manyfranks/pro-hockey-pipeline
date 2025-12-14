"""
NHL SGP Pipeline Runner

Production entry point aligned with NFL/NCAAF architecture:
1. Settle yesterday's parlays (legs + parlay result)
2. Generate today's multi-leg parlays

Usage:
    python -m nhl_sgp_engine.scripts.run_sgp_pipeline
    python -m nhl_sgp_engine.scripts.run_sgp_pipeline --generate-only
    python -m nhl_sgp_engine.scripts.run_sgp_pipeline --settle-only
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from datetime import date, timedelta

from nhl_sgp_engine.scripts.daily_sgp_generator import NHLSGPGenerator
from nhl_sgp_engine.scripts.settle_sgp_parlays import SGPParlaySettlement
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager


def run_full_pipeline(dry_run: bool = False) -> dict:
    """
    Run the full daily SGP pipeline.

    1. Settle yesterday's parlays
    2. Generate today's parlays
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    print("=" * 70)
    print("NHL SGP PIPELINE")
    print(f"Date: {today}")
    print("=" * 70)

    results = {
        'date': str(today),
        'settlement': None,
        'generation': None,
    }

    # Ensure tables exist
    db = NHLSGPDBManager()
    db.create_tables()

    # Step 1: Settle yesterday's parlays
    print("\n" + "=" * 70)
    print("STEP 1: SETTLEMENT")
    print("=" * 70)

    settler = SGPParlaySettlement()
    settlement_result = settler.run(game_date=yesterday)
    results['settlement'] = settlement_result

    # Step 2: Generate today's parlays
    print("\n" + "=" * 70)
    print("STEP 2: PARLAY GENERATION")
    print("=" * 70)

    generator = NHLSGPGenerator()
    generation_result = generator.run(game_date=today, dry_run=dry_run)
    results['generation'] = generation_result

    # Summary
    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)

    if settlement_result:
        print(f"\nSettlement ({yesterday}):")
        print(f"  Parlays settled: {settlement_result.get('settled', 0)}")
        print(f"  Wins: {settlement_result.get('wins', 0)}")
        print(f"  Win rate: {settlement_result.get('win_rate', 0):.1f}%")
        print(f"  Profit: ${settlement_result.get('profit', 0):.2f}")

    if generation_result:
        print(f"\nGeneration ({today}):")
        print(f"  Parlays created: {generation_result.get('parlays', 0)}")
        print(f"  Total legs: {generation_result.get('total_legs', 0)}")

    # Historical performance
    print("\n" + "=" * 70)
    print("HISTORICAL PERFORMANCE")
    print("=" * 70)

    try:
        with db.Session() as session:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT p.id) as total_parlays,
                    SUM(CASE WHEN s.result = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN s.result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    ROUND(AVG(CASE WHEN s.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
                    SUM(COALESCE(s.profit, 0)) as total_profit
                FROM nhl_sgp_parlays p
                LEFT JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
                WHERE s.result IS NOT NULL
            """))
            row = result.fetchone()
            if row and row.total_parlays > 0:
                print(f"  Total parlays: {row.total_parlays}")
                print(f"  Record: {row.wins}W - {row.losses}L")
                print(f"  Win rate: {row.win_rate}%")
                print(f"  Total profit: ${row.total_profit:.2f}")
            else:
                print("  No settled parlays yet")
    except Exception as e:
        print(f"  Could not fetch performance: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description='Run NHL SGP pipeline')
    parser.add_argument('--generate-only', action='store_true', help='Only generate parlays')
    parser.add_argument('--settle-only', action='store_true', help='Only run settlement')
    parser.add_argument('--dry-run', action='store_true', help='Do not write to database')
    parser.add_argument('--date', type=str, help='Override date (YYYY-MM-DD)')
    args = parser.parse_args()

    if args.generate_only:
        generator = NHLSGPGenerator()
        game_date = date.fromisoformat(args.date) if args.date else date.today()
        result = generator.run(game_date=game_date, dry_run=args.dry_run)
        print(f"\n[Pipeline] Generated {result['parlays']} parlays")

    elif args.settle_only:
        settler = SGPParlaySettlement()
        game_date = date.fromisoformat(args.date) if args.date else (date.today() - timedelta(days=1))
        result = settler.run(game_date=game_date)
        print(f"\n[Settlement] Settled {result['settled']} parlays")

    else:
        run_full_pipeline(dry_run=args.dry_run)

    print("\n[Pipeline] Complete")


if __name__ == '__main__':
    main()
