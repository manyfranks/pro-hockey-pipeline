#!/usr/bin/env python3
"""
Expand Backtest Sample

Fetch historical odds for additional dates with settled pipeline predictions.
Target: 5-7 more dates to validate the 62.5% hit rate.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS
from sqlalchemy import text


def expand_sample(target_dates: list, max_games_per_date: int = 5):
    """
    Fetch odds for specific dates.

    Args:
        target_dates: List of date strings (YYYY-MM-DD)
        max_games_per_date: Max games to fetch per date
    """
    print(f"\n{'='*60}")
    print("EXPANDING BACKTEST SAMPLE")
    print(f"{'='*60}")

    client = OddsAPIClient()
    sgp_db = NHLSGPDBManager()

    # Check API budget
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")

    total_props = 0

    for date_str in target_dates:
        print(f"\n--- Fetching {date_str} ---")

        # Check if we already have odds for this date
        with sgp_db.Session() as session:
            result = session.execute(text("""
                SELECT COUNT(*) FROM nhl_sgp_historical_odds
                WHERE game_date = :game_date
            """), {'game_date': date_str})
            existing = result.scalar()

        if existing > 0:
            print(f"  Already have {existing} props, skipping")
            continue

        try:
            # Get events for this date
            events = client.get_historical_events(date_str)
            print(f"  Found {len(events)} events")

            if not events:
                continue

            date_props = []
            for event in events[:max_games_per_date]:
                event_id = event.get('id')
                home = event.get('home_team', '')[:3].upper()
                away = event.get('away_team', '')[:3].upper()

                print(f"  Fetching {away} @ {home}...")

                odds_data = client.get_historical_event_odds(
                    event_id=event_id,
                    date_str=date_str,
                    markets=BACKTEST_MARKETS,
                )

                props = client.parse_player_props(
                    odds_data.get('data', odds_data),
                    market_keys=BACKTEST_MARKETS,
                )

                print(f"    Found {len(props)} props")

                for prop in props:
                    record = {
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
                    }
                    date_props.append(record)

            # Insert to database
            if date_props:
                inserted = sgp_db.bulk_insert_historical_odds(date_props)
                print(f"  Inserted {inserted} props")
                total_props += inserted

        except Exception as e:
            print(f"  Error: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"COMPLETE - Added {total_props} props")
    print(f"{'='*60}")

    # Check new API usage
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")


if __name__ == "__main__":
    # Target dates with settled predictions that we don't have odds for
    # Prioritizing high-volume dates
    target_dates = [
        '2025-12-10',  # 193 players
        '2025-12-08',  # 255 players
        '2025-12-07',  # 392 players
        '2025-12-05',  # 249 players
        '2025-12-04',  # 496 players
    ]

    expand_sample(target_dates, max_games_per_date=5)
