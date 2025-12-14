#!/usr/bin/env python3
"""
Fetch assists props for backtest dates.

Adds player_assists to existing historical odds data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from sqlalchemy import text


def fetch_assists():
    """Fetch assists props for existing backtest dates."""
    print(f"\n{'='*60}")
    print("FETCHING ASSISTS PROPS FOR BACKTEST")
    print(f"{'='*60}")

    client = OddsAPIClient()
    sgp_db = NHLSGPDBManager()

    # Check API budget
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")

    # Get dates we already have historical odds for
    with sgp_db.Session() as session:
        result = session.execute(text('''
            SELECT DISTINCT game_date, event_id, home_team, away_team
            FROM nhl_sgp_historical_odds
            WHERE market_key = 'player_points'
            ORDER BY game_date DESC
        '''))
        events_to_fetch = [(str(row[0]), row[1], row[2], row[3]) for row in result]

    print(f"Found {len(events_to_fetch)} events to fetch assists for")

    # Check if we already have assists
    with sgp_db.Session() as session:
        result = session.execute(text('''
            SELECT COUNT(*) FROM nhl_sgp_historical_odds
            WHERE market_key = 'player_assists'
        '''))
        existing_assists = result.scalar()

    if existing_assists > 0:
        print(f"Already have {existing_assists} assists props, skipping fetch")
        return

    total_props = 0

    for date_str, event_id, home, away in events_to_fetch:
        print(f"\n--- {away} @ {home} ({date_str}) ---")

        try:
            # Fetch assists odds
            odds_data = client.get_historical_event_odds(
                event_id=event_id,
                date_str=date_str,
                markets=['player_assists'],
                use_cache=True,
            )

            props = client.parse_player_props(
                odds_data.get('data', odds_data),
                market_keys=['player_assists'],
            )

            print(f"  Found {len(props)} assists props")

            if props:
                records = []
                for prop in props:
                    records.append({
                        'event_id': event_id,
                        'game_date': datetime.strptime(date_str, '%Y-%m-%d').date(),
                        'home_team': home,
                        'away_team': away,
                        'player_name': prop.player_name,
                        'stat_type': prop.stat_type,
                        'market_key': prop.market_key,
                        'line': prop.line,
                        'over_price': prop.over_price,
                        'under_price': prop.under_price,
                        'bookmaker': prop.bookmaker,
                        'snapshot_time': prop.snapshot_time,
                    })

                # Insert to database
                inserted = sgp_db.bulk_insert_historical_odds(records)
                print(f"  Inserted {inserted} props")
                total_props += inserted

        except Exception as e:
            print(f"  Error: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"COMPLETE - Added {total_props} assists props")
    print(f"{'='*60}")

    # Check new API usage
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")


if __name__ == "__main__":
    fetch_assists()
