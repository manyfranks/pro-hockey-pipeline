#!/usr/bin/env python3
"""
NHL SportsDataIO Endpoint Validation Test Script

This script validates that all required NHL endpoints are accessible and
returns data in the expected format. Run this before starting development
to ensure API access is working correctly.

Usage:
    cd analytics-pro
    python -m nhl_isolated.scripts.test_endpoints

Or:
    python nhl_isolated/scripts/test_endpoints.py
"""
import os
import sys
import json
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

# Load environment variables from .env.local
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env.local')
load_dotenv(env_path)

from nhl_isolated.providers.sportsdataio_nhl import SportsDataIONHLProvider


class EndpointTester:
    """Tests all NHL SportsDataIO endpoints and reports results."""

    def __init__(self):
        self.provider = SportsDataIONHLProvider()
        self.results: List[Dict[str, Any]] = []
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data', 'sample_responses'
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def _save_sample(self, name: str, data: Any) -> None:
        """Save sample response to file for documentation."""
        path = os.path.join(self.output_dir, f"{name}.json")
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"    Saved sample to: {path}")

    def _test_endpoint(self, name: str, func, *args, save_sample: bool = True) -> Dict[str, Any]:
        """Test a single endpoint and record results."""
        result = {
            'endpoint': name,
            'status': 'UNKNOWN',
            'count': 0,
            'error': None,
            'sample_fields': []
        }

        try:
            print(f"\n{'='*60}")
            print(f"Testing: {name}")
            print(f"{'='*60}")

            data = func(*args)

            if data is None:
                result['status'] = 'EMPTY'
                result['error'] = 'Returned None'
            elif isinstance(data, list):
                result['status'] = 'OK'
                result['count'] = len(data)
                if len(data) > 0 and isinstance(data[0], dict):
                    result['sample_fields'] = list(data[0].keys())[:10]
                if save_sample and len(data) > 0:
                    # Save first item as sample
                    self._save_sample(name, data[:3] if len(data) > 3 else data)
            elif isinstance(data, dict):
                result['status'] = 'OK'
                result['count'] = 1
                result['sample_fields'] = list(data.keys())[:10]
                if save_sample:
                    self._save_sample(name, data)
            elif isinstance(data, bool):
                result['status'] = 'OK'
                result['count'] = 1
                result['sample_fields'] = [f"value: {data}"]
            else:
                result['status'] = 'OK'
                result['count'] = 1

            print(f"    Status: {result['status']}")
            print(f"    Count: {result['count']}")
            if result['sample_fields']:
                print(f"    Sample fields: {result['sample_fields']}")

        except Exception as e:
            result['status'] = 'ERROR'
            result['error'] = str(e)
            print(f"    Status: ERROR")
            print(f"    Error: {e}")

        self.results.append(result)
        return result

    def run_all_tests(self) -> None:
        """Run all endpoint tests."""
        print("\n" + "="*80)
        print("NHL SPORTSDATA.IO ENDPOINT VALIDATION")
        print("="*80)

        # Get a test date (today or most recent game day)
        test_date = date.today()

        # Get current season
        current_season = self._test_endpoint(
            'current_season',
            self.provider.get_current_season
        )

        # Determine season string from current season response
        season = '2025'  # Default
        if current_season['status'] == 'OK':
            # Try to extract season from response
            try:
                season_data = self.provider.get_current_season()
                if isinstance(season_data, dict) and 'Season' in season_data:
                    season = str(season_data['Season'])
            except:
                pass

        print(f"\nUsing test date: {test_date}")
        print(f"Using season: {season}")

        # =====================================================================
        # SCHEDULE & GAMES
        # =====================================================================
        print("\n\n" + "-"*40)
        print("SCHEDULE & GAMES")
        print("-"*40)

        self._test_endpoint(
            'games_by_date',
            self.provider.get_games_by_date,
            test_date
        )

        self._test_endpoint(
            'scores_basic',
            self.provider.get_scores_basic,
            test_date
        )

        self._test_endpoint(
            'are_games_in_progress',
            self.provider.are_any_games_in_progress
        )

        # =====================================================================
        # GOALTENDERS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("GOALTENDERS")
        print("-"*40)

        self._test_endpoint(
            'starting_goaltenders',
            self.provider.get_starting_goaltenders,
            test_date
        )

        self._test_endpoint(
            'goalie_depth_charts',
            self.provider.get_goalie_depth_charts
        )

        # =====================================================================
        # ROSTERS & PLAYERS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("ROSTERS & PLAYERS")
        print("-"*40)

        self._test_endpoint(
            'team_roster_EDM',
            self.provider.get_team_roster,
            'EDM'
        )

        self._test_endpoint(
            'active_players',
            self.provider.get_active_players
        )

        self._test_endpoint(
            'all_teams',
            self.provider.get_all_teams
        )

        # =====================================================================
        # LINE COMBINATIONS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("LINE COMBINATIONS")
        print("-"*40)

        self._test_endpoint(
            'line_combinations',
            self.provider.get_line_combinations,
            season
        )

        # =====================================================================
        # PLAYER STATISTICS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("PLAYER STATISTICS")
        print("-"*40)

        self._test_endpoint(
            'player_season_stats',
            self.provider.get_player_season_stats,
            season
        )

        # Test game logs for a specific player (Connor McDavid = 30002576)
        # Note: Player ID may vary - this is an example
        self._test_endpoint(
            'player_game_logs',
            self.provider.get_player_game_logs,
            30002576,  # Example player ID
            season,
            10
        )

        # =====================================================================
        # TEAM STATISTICS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("TEAM STATISTICS")
        print("-"*40)

        self._test_endpoint(
            'team_season_stats',
            self.provider.get_team_season_stats,
            season
        )

        self._test_endpoint(
            'standings',
            self.provider.get_standings,
            season
        )

        # =====================================================================
        # BOX SCORES
        # =====================================================================
        print("\n\n" + "-"*40)
        print("BOX SCORES")
        print("-"*40)

        # Try yesterday for completed games
        yesterday = test_date - timedelta(days=1)
        self._test_endpoint(
            'box_scores_final',
            self.provider.get_box_scores_final,
            yesterday
        )

        # =====================================================================
        # INJURIES & TRANSACTIONS
        # =====================================================================
        print("\n\n" + "-"*40)
        print("INJURIES & TRANSACTIONS")
        print("-"*40)

        self._test_endpoint(
            'injuries',
            self.provider.get_injuries
        )

        self._test_endpoint(
            'transactions',
            self.provider.get_transactions
        )

        # =====================================================================
        # UTILITY
        # =====================================================================
        print("\n\n" + "-"*40)
        print("UTILITY")
        print("-"*40)

        self._test_endpoint(
            'stadiums',
            self.provider.get_stadiums
        )

        # =====================================================================
        # SUMMARY
        # =====================================================================
        self._print_summary()

    def _print_summary(self) -> None:
        """Print test results summary."""
        print("\n\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)

        ok_count = sum(1 for r in self.results if r['status'] == 'OK')
        empty_count = sum(1 for r in self.results if r['status'] == 'EMPTY')
        error_count = sum(1 for r in self.results if r['status'] == 'ERROR')
        total = len(self.results)

        print(f"\nTotal endpoints tested: {total}")
        print(f"  OK:    {ok_count} ({100*ok_count/total:.1f}%)")
        print(f"  EMPTY: {empty_count} ({100*empty_count/total:.1f}%)")
        print(f"  ERROR: {error_count} ({100*error_count/total:.1f}%)")

        if error_count > 0:
            print("\n" + "-"*40)
            print("ERRORS:")
            print("-"*40)
            for r in self.results:
                if r['status'] == 'ERROR':
                    print(f"  {r['endpoint']}: {r['error']}")

        if empty_count > 0:
            print("\n" + "-"*40)
            print("EMPTY RESPONSES (may be expected for no-game days):")
            print("-"*40)
            for r in self.results:
                if r['status'] == 'EMPTY':
                    print(f"  {r['endpoint']}")

        print("\n" + "-"*40)
        print("SUCCESSFUL ENDPOINTS:")
        print("-"*40)
        for r in self.results:
            if r['status'] == 'OK':
                print(f"  {r['endpoint']}: {r['count']} items")

        # Save full results
        results_path = os.path.join(self.output_dir, '_test_results.json')
        with open(results_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nFull results saved to: {results_path}")

        # Overall status
        print("\n" + "="*80)
        if error_count == 0:
            print("PHASE 0 VALIDATION: PASSED")
            print("All endpoints are accessible. Ready to proceed with Phase 1.")
        else:
            print("PHASE 0 VALIDATION: FAILED")
            print(f"Please resolve {error_count} endpoint error(s) before proceeding.")
        print("="*80 + "\n")


def main():
    """Main entry point."""
    print("\nNHL SportsDataIO Endpoint Validation")
    print("Checking API access and response formats...\n")

    api_key = os.getenv('SPORTS_DATA_API_KEY')
    if not api_key:
        print("ERROR: SPORTS_DATA_API_KEY not found in environment.")
        print("Please ensure .env.local contains SPORTS_DATA_API_KEY=your_key")
        sys.exit(1)

    print(f"API Key found: {api_key[:8]}...{api_key[-4:]}")

    tester = EndpointTester()
    tester.run_all_tests()


if __name__ == '__main__':
    main()
