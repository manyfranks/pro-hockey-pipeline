"""
Fetch ALL Markets for November 2025 Backtest

Per user request: "GRAB ALL THE FUCKING PROP TYPES SO WE CAN DETERMINE IF THEY ARE WORTH EXPLORING"

This script fetches EVERY available market from the Odds API to determine
which prop types have edge potential when matched against NHL API data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Any

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient

# =============================================================================
# ALL AVAILABLE MARKETS FROM THE ODDS API
# https://the-odds-api.com/sports-odds-data/betting-markets.html
# =============================================================================

# Game Lines
GAME_MARKETS = [
    'h2h',                    # Moneyline
    'spreads',                # Puck line
    'totals',                 # Game total O/U
]

# Alternate Game Lines
ALTERNATE_GAME_MARKETS = [
    'alternate_spreads',       # Alt puck lines
    'alternate_totals',        # Alt game totals
]

# Team Totals
TEAM_TOTAL_MARKETS = [
    'team_totals',             # Team O/U
    'alternate_team_totals',   # Alt team totals
]

# Period Props
PERIOD_MARKETS = [
    # First Period
    'h2h_p1', 'h2h_3_way_p1', 'spreads_p1', 'totals_p1',
    'alternate_spreads_p1', 'alternate_totals_p1',
    'team_totals_p1', 'alternate_team_totals_p1',
    # Second Period
    'h2h_p2', 'h2h_3_way_p2', 'spreads_p2', 'totals_p2',
    'alternate_spreads_p2', 'alternate_totals_p2',
    'team_totals_p2', 'alternate_team_totals_p2',
    # Third Period
    'h2h_p3', 'h2h_3_way_p3', 'spreads_p3', 'totals_p3',
    'alternate_spreads_p3', 'alternate_totals_p3',
    'team_totals_p3', 'alternate_team_totals_p3',
]

# Player Props - Main
PLAYER_PROP_MARKETS = [
    'player_points',           # Points O/U
    'player_goals',            # Goals O/U
    'player_assists',          # Assists O/U
    'player_shots_on_goal',    # SOG O/U
    'player_blocked_shots',    # Blocked shots O/U
    'player_power_play_points', # PP Points O/U
    'player_total_saves',      # Goalie saves O/U
]

# Player Props - Alternates
PLAYER_PROP_ALTERNATES = [
    'player_points_alternate',
    'player_goals_alternate',
    'player_assists_alternate',
    'player_shots_on_goal_alternate',
    'player_blocked_shots_alternate',
    'player_power_play_points_alternate',
    'player_total_saves_alternate',
]

# Player Props - Goal Scorers
GOAL_SCORER_MARKETS = [
    'player_goal_scorer_anytime',   # Anytime goal scorer
    'player_goal_scorer_first',     # First goal scorer
    'player_goal_scorer_last',      # Last goal scorer
]

# ALL MARKETS COMBINED
ALL_MARKETS = (
    GAME_MARKETS +
    ALTERNATE_GAME_MARKETS +
    TEAM_TOTAL_MARKETS +
    PERIOD_MARKETS +
    PLAYER_PROP_MARKETS +
    PLAYER_PROP_ALTERNATES +
    GOAL_SCORER_MARKETS
)

# Market categories for analysis
MARKET_CATEGORIES = {
    'game_lines': GAME_MARKETS,
    'alternate_game': ALTERNATE_GAME_MARKETS,
    'team_totals': TEAM_TOTAL_MARKETS,
    'period_props': PERIOD_MARKETS,
    'player_props': PLAYER_PROP_MARKETS,
    'player_alternates': PLAYER_PROP_ALTERNATES,
    'goal_scorers': GOAL_SCORER_MARKETS,
}


def get_november_dates() -> List[str]:
    """Get all dates in November 2025."""
    dates = []
    start = date(2025, 11, 1)
    end = date(2025, 11, 30)
    current = start
    while current <= end:
        dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return dates


def fetch_all_markets(
    client: OddsAPIClient,
    game_date: str,
    max_games: int = None,
) -> Dict[str, Any]:
    """
    Fetch ALL available markets for a given date.

    Returns:
        Dict with discovered markets and their data
    """
    result = {
        'date': game_date,
        'events': [],
        'markets_found': {},
        'market_counts': {},
        'total_props': 0,
        'api_calls': 0,
    }

    # Step 1: Get historical events for the date
    print(f"\n  Fetching events for {game_date}...")
    events = client.get_historical_events(game_date, use_cache=True)
    result['api_calls'] += 1

    if not events:
        print(f"    No events found for {game_date}")
        return result

    print(f"    Found {len(events)} events")

    # Limit games if specified
    if max_games:
        events = events[:max_games]

    # Step 2: For each event, fetch ALL markets
    for event in events:
        event_id = event.get('id')
        home = event.get('home_team', 'Unknown')
        away = event.get('away_team', 'Unknown')

        print(f"    {away} @ {home}...")

        event_result = {
            'event_id': event_id,
            'matchup': f"{away}@{home}",
            'markets': {},
        }

        # Fetch each market category separately to discover what's available
        # This avoids hitting API limits on market count per request
        for category, markets in MARKET_CATEGORIES.items():
            try:
                odds_data = client.get_historical_event_odds(
                    event_id=event_id,
                    date_str=game_date,
                    markets=markets,
                    use_cache=True,
                )
                result['api_calls'] += 1

                # Parse the response
                data = odds_data.get('data', odds_data)
                bookmakers = data.get('bookmakers', [])

                for bm in bookmakers:
                    for market in bm.get('markets', []):
                        market_key = market.get('key')
                        outcomes = market.get('outcomes', [])

                        if market_key not in result['markets_found']:
                            result['markets_found'][market_key] = []

                        if market_key not in result['market_counts']:
                            result['market_counts'][market_key] = 0

                        result['market_counts'][market_key] += len(outcomes)
                        result['total_props'] += len(outcomes)

                        # Store a sample
                        for outcome in outcomes[:3]:  # Just first 3 as sample
                            result['markets_found'][market_key].append({
                                'matchup': f"{away}@{home}",
                                'bookmaker': bm.get('key'),
                                'outcome': outcome,
                            })

            except Exception as e:
                if 'not available' not in str(e).lower():
                    print(f"      {category}: error - {e}")

        result['events'].append(event_result)

    return result


def main():
    print("=" * 70)
    print("FETCHING ALL MARKETS - NOVEMBER 2025")
    print("=" * 70)
    print(f"Total market categories: {len(MARKET_CATEGORIES)}")
    print(f"Total individual markets: {len(ALL_MARKETS)}")
    print()

    # List all markets we're looking for
    for category, markets in MARKET_CATEGORIES.items():
        print(f"  {category}: {len(markets)} markets")

    client = OddsAPIClient()

    # Check current usage
    status = client.test_connection()
    print(f"\nAPI Status: {status.get('status')}")
    print(f"Requests remaining: {status.get('requests_remaining')}")

    # Start with a sample - 3 dates from November
    sample_dates = ['2025-11-15', '2025-11-20', '2025-11-25']

    print(f"\n{'='*70}")
    print(f"PHASE 1: MARKET DISCOVERY (3 sample dates)")
    print(f"{'='*70}")

    all_results = []
    all_markets_found = set()
    market_totals = {}

    for game_date in sample_dates:
        result = fetch_all_markets(client, game_date, max_games=2)
        all_results.append(result)

        # Aggregate markets
        for market, count in result['market_counts'].items():
            all_markets_found.add(market)
            market_totals[market] = market_totals.get(market, 0) + count

        print(f"  Date {game_date}: {len(result['markets_found'])} markets, {result['total_props']} props")

    # Summary
    print(f"\n{'='*70}")
    print("MARKET DISCOVERY RESULTS")
    print(f"{'='*70}")
    print(f"\nMarkets actually found in API responses: {len(all_markets_found)}")
    print()

    # Sort by volume
    sorted_markets = sorted(market_totals.items(), key=lambda x: x[1], reverse=True)

    print("Market                          | Volume")
    print("-" * 50)
    for market, count in sorted_markets:
        print(f"{market:30} | {count:>6}")

    # Check API usage
    usage = client.get_usage_summary()
    print(f"\nAPI Usage: {usage['requests_used']} used, {usage['requests_remaining']} remaining")

    # Save results
    output_path = Path(__file__).parent.parent / 'data' / 'market_discovery_november.json'
    output_path.parent.mkdir(exist_ok=True)

    output = {
        'discovered_at': datetime.now().isoformat(),
        'sample_dates': sample_dates,
        'markets_found': list(all_markets_found),
        'market_volumes': market_totals,
        'sample_data': {r['date']: r['markets_found'] for r in all_results},
        'api_usage': usage,
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")

    return sorted_markets


if __name__ == '__main__':
    main()
