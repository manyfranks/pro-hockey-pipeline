"""
The Odds API Client for NHL Player Props

Handles both historical and live odds fetching with budget management.
https://the-odds-api.com/liveapi/guides/v4/
"""
import os
import json
import time
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from ..config.settings import (
    ODDS_API_KEY,
    ODDS_API_BASE_URL,
    NHL_SPORT_KEY,
    REGIONS,
    API_COST_HISTORICAL_EVENTS,
    API_COST_HISTORICAL_ODDS,
    ODDS_CACHE_DIR,
)
from ..config.markets import BACKTEST_MARKETS, PRIMARY_BOOKMAKER


@dataclass
class APIUsage:
    """Track API usage for budget management."""
    requests_used: int = 0
    requests_remaining: int = 0
    last_request_cost: int = 0


@dataclass
class PlayerProp:
    """Standardized player prop structure."""
    event_id: str
    player_name: str
    player_id: Optional[str]  # If available from API
    team: str
    stat_type: str            # e.g., 'points', 'goals'
    market_key: str           # e.g., 'player_points'
    line: float               # e.g., 0.5, 1.5
    over_price: int           # American odds
    under_price: int          # American odds
    bookmaker: str
    snapshot_time: str        # ISO timestamp


class OddsAPIClient:
    """
    Client for The Odds API - Historical and Live NHL Odds.

    Budget-conscious design:
    - Caches responses to disk
    - Tracks API usage
    - Provides cost estimates before fetching
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or ODDS_API_KEY
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not configured")

        self.base_url = ODDS_API_BASE_URL
        self.sport = NHL_SPORT_KEY
        self.session = requests.Session()
        self.usage = APIUsage()
        self.cache_dir = ODDS_CACHE_DIR

    def _make_request(self, endpoint: str, params: Dict = None) -> Tuple[Dict, int]:
        """
        Make API request and track usage.

        Returns:
            Tuple of (response_data, request_cost)
        """
        url = f"{self.base_url}/{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key

        response = self.session.get(url, params=params)

        # Track usage from headers (values come as floats like "16418.0")
        used_str = response.headers.get('x-requests-used', '0')
        remaining_str = response.headers.get('x-requests-remaining', '0')
        self.usage.requests_used = int(float(used_str)) if used_str else 0
        self.usage.requests_remaining = int(float(remaining_str)) if remaining_str else 0

        if response.status_code == 429:
            raise Exception(f"Rate limited. Remaining: {self.usage.requests_remaining}")

        response.raise_for_status()
        return response.json(), self.usage.requests_used

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get cache file path for a given key."""
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> Optional[Dict]:
        """Read from cache if exists."""
        cache_path = self._get_cache_path(cache_key)
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return None

    def _write_cache(self, cache_key: str, data: Dict):
        """Write to cache."""
        cache_path = self._get_cache_path(cache_key)
        with open(cache_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    # =========================================================================
    # Current/Live Odds
    # =========================================================================

    def get_current_events(self) -> List[Dict]:
        """
        Get current/upcoming NHL events.

        Returns:
            List of event objects with id, sport_key, commence_time, teams
        """
        data, _ = self._make_request(f"sports/{self.sport}/events")
        return data

    def get_current_odds(
        self,
        markets: List[str] = None,
        regions: List[str] = None,
        bookmakers: List[str] = None,
    ) -> List[Dict]:
        """
        Get current odds for all upcoming NHL games.

        Args:
            markets: List of market keys (e.g., ['player_points', 'player_goals'])
            regions: List of regions (e.g., ['us'])
            bookmakers: Optional list of specific bookmakers

        Returns:
            List of event objects with odds
        """
        markets = markets or BACKTEST_MARKETS
        regions = regions or REGIONS

        params = {
            'regions': ','.join(regions),
            'markets': ','.join(markets),
            'oddsFormat': 'american',
        }
        if bookmakers:
            params['bookmakers'] = ','.join(bookmakers)

        data, _ = self._make_request(f"sports/{self.sport}/odds", params)
        return data

    def get_event_odds(
        self,
        event_id: str,
        markets: List[str] = None,
        regions: List[str] = None,
    ) -> Dict:
        """
        Get odds for a specific event.

        Args:
            event_id: The event ID from get_current_events()
            markets: List of market keys
            regions: List of regions

        Returns:
            Event object with odds
        """
        markets = markets or BACKTEST_MARKETS
        regions = regions or REGIONS

        params = {
            'regions': ','.join(regions),
            'markets': ','.join(markets),
            'oddsFormat': 'american',
        }

        data, _ = self._make_request(
            f"sports/{self.sport}/events/{event_id}/odds",
            params
        )
        return data

    # =========================================================================
    # Historical Odds (for backtesting)
    # =========================================================================

    def get_historical_events(
        self,
        date_str: str,
        use_cache: bool = True,
    ) -> List[Dict]:
        """
        Get historical NHL events for a specific date.

        Cost: 1 API call

        Args:
            date_str: Date in YYYY-MM-DD format
            use_cache: Whether to use cached data

        Returns:
            List of historical event objects
        """
        cache_key = f"hist_events_{date_str}"

        if use_cache:
            cached = self._read_cache(cache_key)
            if cached:
                return cached.get('data', [])

        # Format date for API (needs timestamp)
        date_timestamp = f"{date_str}T12:00:00Z"

        params = {'date': date_timestamp}
        data, _ = self._make_request(
            f"historical/sports/{self.sport}/events",
            params
        )

        # Cache the response
        self._write_cache(cache_key, data)

        return data.get('data', [])

    def get_historical_event_odds(
        self,
        event_id: str,
        date_str: str,
        markets: List[str] = None,
        regions: List[str] = None,
        use_cache: bool = True,
    ) -> Dict:
        """
        Get historical odds for a specific event.

        Cost: 10 per region per market
        With 1 region, 2 markets = 20 calls

        Args:
            event_id: Historical event ID
            date_str: Snapshot date in YYYY-MM-DD format
            markets: List of market keys
            regions: List of regions
            use_cache: Whether to use cached data

        Returns:
            Event odds snapshot with timestamp info
        """
        import hashlib
        markets = markets or BACKTEST_MARKETS
        regions = regions or REGIONS

        # Use hash for long market lists to avoid filename length issues
        markets_str = '_'.join(sorted(markets))
        if len(markets_str) > 50:
            markets_hash = hashlib.md5(markets_str.encode()).hexdigest()[:12]
            cache_key = f"hist_odds_{event_id}_{date_str}_{markets_hash}"
        else:
            cache_key = f"hist_odds_{event_id}_{date_str}_{markets_str}"

        if use_cache:
            cached = self._read_cache(cache_key)
            if cached:
                return cached

        # Pre-game snapshot (6 hours before typical game time)
        snapshot_time = f"{date_str}T18:00:00Z"

        params = {
            'regions': ','.join(regions),
            'markets': ','.join(markets),
            'oddsFormat': 'american',
            'date': snapshot_time,
        }

        data, _ = self._make_request(
            f"historical/sports/{self.sport}/events/{event_id}/odds",
            params
        )

        # Cache the response
        self._write_cache(cache_key, data)

        return data

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def estimate_backfill_cost(
        self,
        num_games: int,
        markets: List[str] = None,
        regions: List[str] = None,
    ) -> Dict:
        """
        Estimate API cost for a backfill operation.

        Args:
            num_games: Number of games to fetch odds for
            markets: List of markets (default: BACKTEST_MARKETS)
            regions: List of regions (default: REGIONS)

        Returns:
            Cost breakdown dictionary
        """
        markets = markets or BACKTEST_MARKETS
        regions = regions or REGIONS

        # Cost per game = 10 * num_regions * num_markets
        cost_per_game = API_COST_HISTORICAL_ODDS * len(regions) * len(markets)

        # Add cost for historical events queries (1 per day)
        # Assume average of 8 games per day
        num_days = max(1, num_games // 8)
        events_cost = num_days * API_COST_HISTORICAL_EVENTS

        total_cost = (num_games * cost_per_game) + events_cost

        return {
            'num_games': num_games,
            'num_markets': len(markets),
            'num_regions': len(regions),
            'cost_per_game': cost_per_game,
            'events_cost': events_cost,
            'total_cost': total_cost,
            'remaining_budget': self.usage.requests_remaining,
        }

    def parse_player_props(
        self,
        event_data: Dict,
        market_keys: List[str] = None,
        bookmaker: str = None,
    ) -> List[PlayerProp]:
        """
        Parse event odds response into standardized PlayerProp objects.

        Args:
            event_data: Event odds response from API
            market_keys: Filter to specific markets
            bookmaker: Filter to specific bookmaker

        Returns:
            List of PlayerProp objects
        """
        from ..config.markets import MARKET_TO_STAT_TYPE

        props = []
        event_id = event_data.get('id', '')

        # Get teams
        home_team = event_data.get('home_team', '')
        away_team = event_data.get('away_team', '')

        # Get snapshot time if historical
        snapshot_time = event_data.get('timestamp', datetime.utcnow().isoformat())

        bookmakers_data = event_data.get('bookmakers', [])

        for bm in bookmakers_data:
            bm_key = bm.get('key', '')

            # Filter by bookmaker if specified
            if bookmaker and bm_key != bookmaker:
                continue

            for market in bm.get('markets', []):
                market_key = market.get('key', '')

                # Filter by market if specified
                if market_keys and market_key not in market_keys:
                    continue

                # Skip non-player-prop markets
                if not market_key.startswith('player_'):
                    continue

                stat_type = MARKET_TO_STAT_TYPE.get(market_key, market_key)

                for outcome in market.get('outcomes', []):
                    # Player props have 'description' (player name) and 'name' (Over/Under)
                    player_name = outcome.get('description', '')
                    direction = outcome.get('name', '').lower()  # 'Over' or 'Under'
                    price = outcome.get('price', 0)
                    line = outcome.get('point', 0.5)

                    if not player_name:
                        continue

                    # Determine team (not always available in API)
                    # Will need to match against roster data
                    team = ''

                    # For player props, we get Over and Under as separate outcomes
                    # Group them by player + line
                    if direction == 'over':
                        # Find matching under
                        under_price = None
                        for other in market.get('outcomes', []):
                            if (other.get('description') == player_name and
                                other.get('name', '').lower() == 'under' and
                                other.get('point') == line):
                                under_price = other.get('price')
                                break

                        props.append(PlayerProp(
                            event_id=event_id,
                            player_name=player_name,
                            player_id=None,
                            team=team,
                            stat_type=stat_type,
                            market_key=market_key,
                            line=line,
                            over_price=price,
                            under_price=under_price or 0,
                            bookmaker=bm_key,
                            snapshot_time=snapshot_time,
                        ))

        return props

    def get_usage_summary(self) -> Dict:
        """Get current API usage summary."""
        return {
            'requests_used': self.usage.requests_used,
            'requests_remaining': self.usage.requests_remaining,
            'last_cost': self.usage.last_request_cost,
        }

    def test_connection(self) -> Dict:
        """
        Test API connection and return status.

        Returns:
            Dict with connection status and usage info
        """
        try:
            # Make a minimal request (sports list is free)
            data, _ = self._make_request("sports")

            # Find NHL in the response
            nhl_active = any(
                s.get('key') == self.sport and s.get('active', False)
                for s in data
            )

            return {
                'status': 'connected',
                'nhl_active': nhl_active,
                'requests_remaining': self.usage.requests_remaining,
                'requests_used': self.usage.requests_used,
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
            }
