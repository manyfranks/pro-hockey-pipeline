"""
Historical Data Loader for NHL SGP Backtesting

Loads historical odds from The Odds API and outcomes from NHL API.
Budget-conscious with progress tracking and resume capability.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import time
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient, PlayerProp
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.settings import (
    API_BUDGET_NHL_SGP,
    API_COST_HISTORICAL_ODDS,
    DATA_DIR,
)
from nhl_sgp_engine.config.markets import BACKTEST_MARKETS


@dataclass
class LoaderProgress:
    """Track loader progress for resume capability."""
    total_dates: int = 0
    processed_dates: int = 0
    total_games: int = 0
    processed_games: int = 0
    total_props: int = 0
    api_calls_used: int = 0
    last_date: str = ""
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class HistoricalLoader:
    """
    Loads historical odds data for NHL SGP backtesting.

    Features:
    - Budget management (respects API call limits)
    - Resume capability (saves progress)
    - Caching (avoids duplicate API calls)
    - Batch processing (database efficiency)
    """

    PROGRESS_FILE = DATA_DIR / "backfill_progress.json"
    COST_PER_GAME = API_COST_HISTORICAL_ODDS * len(BACKTEST_MARKETS)  # 20 calls

    def __init__(
        self,
        api_budget: int = API_BUDGET_NHL_SGP,
        markets: List[str] = None,
    ):
        self.odds_client = OddsAPIClient()
        self.db = NHLSGPDBManager()
        self.api_budget = api_budget
        self.markets = markets or BACKTEST_MARKETS
        self.progress = self._load_progress()

    def _load_progress(self) -> LoaderProgress:
        """Load progress from file for resume capability."""
        if self.PROGRESS_FILE.exists():
            with open(self.PROGRESS_FILE, 'r') as f:
                data = json.load(f)
                return LoaderProgress(**data)
        return LoaderProgress()

    def _save_progress(self):
        """Save progress for resume capability."""
        with open(self.PROGRESS_FILE, 'w') as f:
            json.dump(asdict(self.progress), f, indent=2)

    def _get_date_range(
        self,
        start_date: str,
        end_date: str,
        resume: bool = True,
    ) -> List[str]:
        """
        Generate list of dates to process.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            resume: If True, skip already processed dates
        """
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        dates = []
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")

            # Skip if already processed and resume is enabled
            if resume and self.progress.last_date and date_str <= self.progress.last_date:
                current += timedelta(days=1)
                continue

            dates.append(date_str)
            current += timedelta(days=1)

        return dates

    def estimate_cost(
        self,
        start_date: str,
        end_date: str,
        avg_games_per_day: int = 8,
    ) -> Dict:
        """
        Estimate API cost for a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            avg_games_per_day: Average NHL games per day

        Returns:
            Cost estimate dictionary
        """
        dates = self._get_date_range(start_date, end_date, resume=False)
        num_days = len(dates)
        estimated_games = num_days * avg_games_per_day

        # Events calls (1 per day)
        events_cost = num_days

        # Odds calls (20 per game for 2 markets)
        odds_cost = estimated_games * self.COST_PER_GAME

        total_cost = events_cost + odds_cost

        return {
            'num_days': num_days,
            'estimated_games': estimated_games,
            'events_cost': events_cost,
            'odds_cost': odds_cost,
            'total_cost': total_cost,
            'budget': self.api_budget,
            'within_budget': total_cost <= self.api_budget,
            'max_games_in_budget': (self.api_budget - events_cost) // self.COST_PER_GAME,
        }

    def load_historical_data(
        self,
        start_date: str,
        end_date: str,
        max_games: int = None,
        dry_run: bool = False,
    ) -> LoaderProgress:
        """
        Load historical odds data for a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_games: Maximum games to process (budget safety)
            dry_run: If True, don't make API calls or save to DB

        Returns:
            LoaderProgress with results
        """
        dates = self._get_date_range(start_date, end_date)
        self.progress.total_dates = len(dates)

        # Calculate max games based on budget
        if max_games is None:
            estimate = self.estimate_cost(start_date, end_date)
            max_games = estimate['max_games_in_budget']

        print(f"\n{'='*60}")
        print(f"HISTORICAL DATA LOAD")
        print(f"{'='*60}")
        print(f"Date range: {start_date} to {end_date}")
        print(f"Dates to process: {len(dates)}")
        print(f"Max games: {max_games}")
        print(f"Markets: {', '.join(self.markets)}")
        print(f"Dry run: {dry_run}")
        print(f"{'='*60}\n")

        games_processed = 0
        all_props = []

        for date_str in dates:
            if games_processed >= max_games:
                print(f"\nReached max games limit ({max_games}). Stopping.")
                break

            print(f"\n--- Processing {date_str} ---")

            try:
                # Fetch historical events for this date
                if not dry_run:
                    events = self.odds_client.get_historical_events(date_str)
                    self.progress.api_calls_used += 1
                else:
                    events = []
                    print("  [DRY RUN] Would fetch events")

                print(f"  Found {len(events)} events")

                for event in events:
                    if games_processed >= max_games:
                        break

                    event_id = event.get('id')
                    home_team = event.get('home_team', '')
                    away_team = event.get('away_team', '')

                    print(f"  Game: {away_team} @ {home_team}")

                    if not dry_run:
                        # Fetch odds for this event
                        try:
                            odds_data = self.odds_client.get_historical_event_odds(
                                event_id=event_id,
                                date_str=date_str,
                                markets=self.markets,
                            )
                            self.progress.api_calls_used += self.COST_PER_GAME

                            # Parse props
                            props = self.odds_client.parse_player_props(
                                odds_data.get('data', odds_data),
                                market_keys=self.markets,
                            )

                            print(f"    Found {len(props)} player props")

                            # Convert to DB records
                            for prop in props:
                                record = {
                                    'event_id': event_id,
                                    'game_date': datetime.strptime(date_str, "%Y-%m-%d").date(),
                                    'home_team': self._abbrev_team(home_team),
                                    'away_team': self._abbrev_team(away_team),
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
                            error_msg = f"Error fetching odds for {event_id}: {e}"
                            print(f"    ERROR: {e}")
                            self.progress.errors.append(error_msg)
                            continue

                    else:
                        print(f"    [DRY RUN] Would fetch odds (cost: {self.COST_PER_GAME} calls)")

                    games_processed += 1
                    self.progress.processed_games = games_processed

                # Batch insert props
                if all_props and not dry_run:
                    inserted = self.db.bulk_insert_historical_odds(all_props)
                    print(f"  Inserted {inserted} props to database")
                    self.progress.total_props += inserted
                    all_props = []

                self.progress.last_date = date_str
                self.progress.processed_dates += 1
                self._save_progress()

                # Rate limiting
                time.sleep(0.5)

            except Exception as e:
                error_msg = f"Error processing {date_str}: {e}"
                print(f"  ERROR: {e}")
                self.progress.errors.append(error_msg)
                continue

        # Final batch insert
        if all_props and not dry_run:
            inserted = self.db.bulk_insert_historical_odds(all_props)
            self.progress.total_props += inserted

        self._save_progress()

        print(f"\n{'='*60}")
        print("LOAD COMPLETE")
        print(f"{'='*60}")
        print(f"Dates processed: {self.progress.processed_dates}/{self.progress.total_dates}")
        print(f"Games processed: {self.progress.processed_games}")
        print(f"Props loaded: {self.progress.total_props}")
        print(f"API calls used: {self.progress.api_calls_used}")
        print(f"Errors: {len(self.progress.errors)}")

        return self.progress

    def _abbrev_team(self, full_name: str) -> str:
        """Convert full team name to abbreviation."""
        # Common NHL team abbreviations
        TEAM_ABBREVS = {
            'Anaheim Ducks': 'ANA',
            'Arizona Coyotes': 'ARI',
            'Boston Bruins': 'BOS',
            'Buffalo Sabres': 'BUF',
            'Calgary Flames': 'CGY',
            'Carolina Hurricanes': 'CAR',
            'Chicago Blackhawks': 'CHI',
            'Colorado Avalanche': 'COL',
            'Columbus Blue Jackets': 'CBJ',
            'Dallas Stars': 'DAL',
            'Detroit Red Wings': 'DET',
            'Edmonton Oilers': 'EDM',
            'Florida Panthers': 'FLA',
            'Los Angeles Kings': 'LAK',
            'Minnesota Wild': 'MIN',
            'Montreal Canadiens': 'MTL',
            'Nashville Predators': 'NSH',
            'New Jersey Devils': 'NJD',
            'New York Islanders': 'NYI',
            'New York Rangers': 'NYR',
            'Ottawa Senators': 'OTT',
            'Philadelphia Flyers': 'PHI',
            'Pittsburgh Penguins': 'PIT',
            'San Jose Sharks': 'SJS',
            'Seattle Kraken': 'SEA',
            'St. Louis Blues': 'STL',
            'Tampa Bay Lightning': 'TBL',
            'Toronto Maple Leafs': 'TOR',
            'Utah Hockey Club': 'UTA',
            'Vancouver Canucks': 'VAN',
            'Vegas Golden Knights': 'VGK',
            'Washington Capitals': 'WSH',
            'Winnipeg Jets': 'WPG',
        }
        return TEAM_ABBREVS.get(full_name, full_name[:3].upper())

    def load_outcomes_from_nhl_api(
        self,
        start_date: str,
        end_date: str,
    ) -> int:
        """
        Load actual game outcomes from NHL API to settle props.

        Uses the existing NHL pipeline's data if available.

        Returns:
            Number of props settled
        """
        # Import the existing NHL API client
        try:
            from providers.nhl_official_api import NHLOfficialAPI
            nhl_api = NHLOfficialAPI()
        except ImportError:
            print("NHL Official API not available. Cannot load outcomes.")
            return 0

        # Get unsettled props
        unsettled = self.db.get_unsettled_historical_odds(
            start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
            end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
        )

        print(f"\nSettling {len(unsettled)} historical props...")

        # Group by game date
        by_date = {}
        for prop in unsettled:
            d = str(prop['game_date'])
            if d not in by_date:
                by_date[d] = []
            by_date[d].append(prop)

        settlements = []

        for game_date, props in by_date.items():
            print(f"  Processing {game_date} ({len(props)} props)")

            try:
                # Get box scores for this date
                box_scores = nhl_api.get_box_scores(game_date)

                # Build player stats lookup
                player_stats = {}
                for game in box_scores:
                    for player in game.get('player_stats', []):
                        name = player.get('name', '')
                        player_stats[name] = {
                            'points': player.get('points', 0),
                            'goals': player.get('goals', 0),
                            'assists': player.get('assists', 0),
                            'shots': player.get('shots', 0),
                        }

                # Match props to outcomes
                for prop in props:
                    player_name = prop['player_name']
                    stat_type = prop['stat_type']
                    line = float(prop['line']) if prop['line'] else 0.5

                    stats = player_stats.get(player_name)
                    if not stats:
                        continue

                    actual_value = stats.get(stat_type, 0)
                    over_hit = actual_value > line

                    settlements.append({
                        'id': prop['id'],
                        'actual_value': actual_value,
                        'over_hit': over_hit,
                    })

            except Exception as e:
                print(f"    Error: {e}")
                continue

        # Update database
        if settlements:
            self.db.settle_historical_odds(settlements)

        print(f"Settled {len(settlements)} props")
        return len(settlements)


def main():
    """CLI for historical data loading."""
    import argparse

    parser = argparse.ArgumentParser(description='Load historical NHL odds data')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--max-games', type=int, help='Max games to process')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no API calls)')
    parser.add_argument('--estimate', action='store_true', help='Just show cost estimate')

    args = parser.parse_args()

    loader = HistoricalLoader()

    if args.estimate:
        estimate = loader.estimate_cost(args.start, args.end)
        print("\nCost Estimate:")
        for k, v in estimate.items():
            print(f"  {k}: {v}")
        return

    loader.load_historical_data(
        start_date=args.start,
        end_date=args.end,
        max_games=args.max_games,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
