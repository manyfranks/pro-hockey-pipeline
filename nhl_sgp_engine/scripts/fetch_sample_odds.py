#!/usr/bin/env python3
"""
Fetch a small sample of historical odds to test the full pipeline.

Uses minimal API calls (1 day = ~1 event call + ~160 odds calls for 8 games).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS


def fetch_sample():
    """Fetch one day of historical odds as a sample."""

    # Use a date with known NHL games
    sample_date = "2024-12-01"

    print(f"\n{'='*60}")
    print(f"FETCHING SAMPLE ODDS FOR {sample_date}")
    print(f"{'='*60}")

    client = OddsAPIClient()
    db = NHLSGPDBManager()

    # Check current usage
    status = client.test_connection()
    print(f"\nAPI Status:")
    print(f"  Requests remaining: {status.get('requests_remaining')}")

    # Get events for this date
    print(f"\n--- Fetching events for {sample_date} ---")
    events = client.get_historical_events(sample_date)
    print(f"Found {len(events)} events")

    if not events:
        print("No events found. Try a different date.")
        return

    # Limit to first 2 games for sample
    sample_events = events[:2]
    all_props = []

    for event in sample_events:
        event_id = event.get('id')
        home = event.get('home_team', 'Unknown')
        away = event.get('away_team', 'Unknown')

        print(f"\n--- {away} @ {home} ---")
        print(f"Event ID: {event_id}")

        try:
            # Fetch odds
            odds_data = client.get_historical_event_odds(
                event_id=event_id,
                date_str=sample_date,
                markets=BACKTEST_MARKETS,
            )

            # Parse props
            data = odds_data.get('data', odds_data)
            props = client.parse_player_props(data, market_keys=BACKTEST_MARKETS)

            print(f"Found {len(props)} player props")

            if props:
                # Show sample props
                print("\nSample props:")
                for prop in props[:5]:
                    print(f"  {prop.player_name}: {prop.stat_type} {prop.line}")
                    print(f"    Over: {prop.over_price}, Under: {prop.under_price}")
                    print(f"    Book: {prop.bookmaker}")

                # Convert to DB records
                for prop in props:
                    record = {
                        'event_id': event_id,
                        'game_date': datetime.strptime(sample_date, "%Y-%m-%d").date(),
                        'home_team': home[:3].upper(),
                        'away_team': away[:3].upper(),
                        'player_name': prop.player_name,
                        'stat_type': prop.stat_type,
                        'market_key': prop.market_key,
                        'line': prop.line,
                        'over_price': prop.over_price,
                        'under_price': prop.under_price,
                        'bookmaker': prop.bookmaker,
                        'snapshot_time': prop.snapshot_time,
                    }
                    all_props.append(record)

        except Exception as e:
            print(f"Error: {e}")
            continue

    # Insert to database
    if all_props:
        print(f"\n--- Inserting {len(all_props)} props to database ---")
        inserted = db.bulk_insert_historical_odds(all_props)
        print(f"Inserted: {inserted}")

    # Check final usage
    print(f"\n--- Final API Usage ---")
    usage = client.get_usage_summary()
    print(f"Requests remaining: {usage['requests_remaining']}")

    print(f"\n{'='*60}")
    print("SAMPLE FETCH COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    fetch_sample()
