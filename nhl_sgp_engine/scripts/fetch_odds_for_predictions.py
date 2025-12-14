#!/usr/bin/env python3
"""
Fetch Historical Odds for Dates with Pipeline Predictions

Targeted fetch to get odds data for dates where we have
pipeline predictions (and ideally settlements).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS


def fetch_odds_for_predictions(
    num_dates: int = 5,
    max_games_per_date: int = 5,
    skip_dates_with_odds: bool = True,
):
    """
    Fetch odds for dates that have pipeline predictions.

    Args:
        num_dates: Number of dates to fetch
        max_games_per_date: Max games to fetch per date
        skip_dates_with_odds: Skip dates that already have odds data
    """
    print(f"\n{'='*60}")
    print("FETCHING ODDS FOR PIPELINE PREDICTION DATES")
    print(f"{'='*60}")

    client = OddsAPIClient()
    pipeline = PipelineAdapter()
    sgp_db = NHLSGPDBManager()

    # Get API budget
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")

    # Get dates with settled predictions
    from sqlalchemy import text
    with pipeline.Session() as session:
        result = session.execute(text("""
            SELECT DISTINCT analysis_date
            FROM nhl_daily_predictions
            WHERE point_outcome IS NOT NULL
            ORDER BY analysis_date DESC
            LIMIT 30
        """))
        prediction_dates = [row.analysis_date for row in result]

    print(f"Found {len(prediction_dates)} dates with settled predictions")

    # Check which dates already have odds
    dates_to_fetch = []
    for d in prediction_dates:
        if len(dates_to_fetch) >= num_dates:
            break

        # Check if we have odds for this date
        with sgp_db.Session() as session:
            result = session.execute(text("""
                SELECT COUNT(*) FROM nhl_sgp_historical_odds
                WHERE game_date = :game_date
            """), {'game_date': d})
            count = result.scalar()

        if count > 0 and skip_dates_with_odds:
            print(f"  {d}: Already has {count} odds, skipping")
            continue

        dates_to_fetch.append(d)

    print(f"\nWill fetch odds for {len(dates_to_fetch)} dates")
    print(f"Estimated cost: ~{len(dates_to_fetch) * max_games_per_date * 20} API calls")

    if not dates_to_fetch:
        print("No dates to fetch!")
        return

    # Confirm
    confirm = input("\nProceed? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted")
        return

    total_props = 0

    for game_date in dates_to_fetch:
        date_str = game_date.strftime("%Y-%m-%d")
        print(f"\n--- Fetching {date_str} ---")

        try:
            # Get events for this date
            events = client.get_historical_events(date_str)
            print(f"  Found {len(events)} events")

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
                        'game_date': game_date,
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
    print(f"COMPLETE - Loaded {total_props} props")
    print(f"{'='*60}")

    # Check new API usage
    status = client.test_connection()
    print(f"API calls remaining: {status['requests_remaining']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--dates', type=int, default=5, help='Number of dates')
    parser.add_argument('--games', type=int, default=5, help='Games per date')
    parser.add_argument('--force', action='store_true', help='Fetch even if data exists')

    args = parser.parse_args()

    fetch_odds_for_predictions(
        num_dates=args.dates,
        max_games_per_date=args.games,
        skip_dates_with_odds=not args.force,
    )
