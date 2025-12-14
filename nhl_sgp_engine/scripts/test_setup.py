#!/usr/bin/env python3
"""
NHL SGP Engine - Setup Test Script

Validates:
1. API connectivity and remaining budget
2. Database connection and schema creation
3. Sample data fetch (minimal API usage)

Run this first to ensure everything is configured correctly.
"""
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date, timedelta
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.settings import API_BUDGET_NHL_SGP
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS


def test_api_connection():
    """Test Odds API connection and check budget."""
    print("\n" + "="*60)
    print("TESTING ODDS API CONNECTION")
    print("="*60)

    try:
        client = OddsAPIClient()
        status = client.test_connection()

        print(f"Status: {status['status']}")
        print(f"NHL Active: {status.get('nhl_active', 'N/A')}")
        print(f"Requests Used: {status.get('requests_used', 'N/A')}")
        print(f"Requests Remaining: {status.get('requests_remaining', 'N/A')}")

        if status['status'] == 'connected':
            remaining = status.get('requests_remaining', 0)
            print(f"\nBudget Check:")
            print(f"  Allocated for NHL SGP: {API_BUDGET_NHL_SGP}")
            print(f"  Available: {remaining}")

            if remaining < API_BUDGET_NHL_SGP:
                print(f"  WARNING: Available < Allocated!")
            else:
                print(f"  OK to proceed with backfill")

            return True, client
        else:
            print(f"Error: {status.get('error', 'Unknown')}")
            return False, None

    except Exception as e:
        print(f"Failed: {e}")
        return False, None


def test_database_connection():
    """Test database connection and create schema."""
    print("\n" + "="*60)
    print("TESTING DATABASE CONNECTION")
    print("="*60)

    try:
        db = NHLSGPDBManager()

        if db.test_connection():
            print("Database connection: OK")

            print("\nCreating/verifying NHL SGP tables...")
            db.create_tables()

            return True, db
        else:
            print("Database connection: FAILED")
            return False, None

    except Exception as e:
        print(f"Failed: {e}")
        return False, None


def test_sample_fetch(client: OddsAPIClient):
    """
    Fetch a small sample to validate API responses.
    Uses cached data if available to save API calls.
    """
    print("\n" + "="*60)
    print("TESTING SAMPLE DATA FETCH")
    print("="*60)

    # Try to get current events (this is a lightweight call)
    try:
        print("\nFetching current NHL events...")
        events = client.get_current_events()
        print(f"Found {len(events)} upcoming/current events")

        if events:
            sample = events[0]
            print(f"\nSample event:")
            print(f"  ID: {sample.get('id')}")
            print(f"  Teams: {sample.get('away_team')} @ {sample.get('home_team')}")
            print(f"  Time: {sample.get('commence_time')}")

        # Estimate backfill cost
        print("\n" + "-"*40)
        print("BACKFILL COST ESTIMATE")
        print("-"*40)

        estimate = client.estimate_backfill_cost(
            num_games=150,  # Target for 3k budget
            markets=BACKTEST_MARKETS,
        )

        print(f"Target games: {estimate['num_games']}")
        print(f"Markets: {estimate['num_markets']} ({', '.join(BACKTEST_MARKETS)})")
        print(f"Cost per game: {estimate['cost_per_game']} calls")
        print(f"Events queries: ~{estimate['events_cost']} calls")
        print(f"Total estimated: {estimate['total_cost']} calls")
        print(f"Budget allocated: {API_BUDGET_NHL_SGP} calls")

        if estimate['total_cost'] <= API_BUDGET_NHL_SGP:
            print("WITHIN BUDGET")
        else:
            max_games = (API_BUDGET_NHL_SGP - estimate['events_cost']) // estimate['cost_per_game']
            print(f"OVER BUDGET - Reduce to ~{max_games} games")

        return True

    except Exception as e:
        print(f"Failed: {e}")
        return False


def test_historical_sample(client: OddsAPIClient):
    """
    Test fetching historical events for a sample date.
    Uses cache to avoid repeat API calls.
    """
    print("\n" + "="*60)
    print("TESTING HISTORICAL DATA ACCESS")
    print("="*60)

    # Use a date we know had NHL games
    sample_date = "2024-11-15"

    try:
        print(f"\nFetching historical events for {sample_date}...")
        print("(Using cache if available)")

        events = client.get_historical_events(sample_date, use_cache=True)
        print(f"Found {len(events)} events")

        if events:
            print(f"\nSample historical events:")
            for i, event in enumerate(events[:3]):
                print(f"  {i+1}. {event.get('away_team')} @ {event.get('home_team')}")
                print(f"     ID: {event.get('id')}")
                print(f"     Time: {event.get('commence_time')}")

        return True, events

    except Exception as e:
        print(f"Failed: {e}")
        return False, []


def main():
    """Run all setup tests."""
    print("\n" + "#"*60)
    print("# NHL SGP ENGINE - SETUP VALIDATION")
    print("#"*60)

    results = {}

    # Test API
    api_ok, client = test_api_connection()
    results['api'] = api_ok

    # Test Database
    db_ok, db = test_database_connection()
    results['database'] = db_ok

    # Test sample fetch (only if API is OK)
    if api_ok:
        results['sample_fetch'] = test_sample_fetch(client)
        hist_ok, events = test_historical_sample(client)
        results['historical'] = hist_ok

    # Summary
    print("\n" + "="*60)
    print("SETUP VALIDATION SUMMARY")
    print("="*60)

    all_ok = True
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test}: {status}")
        if not passed:
            all_ok = False

    print("\n" + "-"*40)
    if all_ok:
        print("All tests passed! Ready to proceed with backfill.")
        print("\nNext steps:")
        print("  1. Run: python -m nhl_sgp_engine.scripts.backfill_historical")
        print("  2. Or test with: python -m nhl_sgp_engine.scripts.fetch_sample_odds")
    else:
        print("Some tests failed. Please fix issues before proceeding.")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
