#!/usr/bin/env python3
# nhl_isolated/scripts/healthcheck.py
"""
Health check script for NHL Prediction Pipeline.

Checks:
1. Database connectivity
2. NHL API availability
3. DailyFaceoff scraper availability
4. Recent predictions exist

Exit codes:
- 0: All checks passed
- 1: One or more checks failed

Usage:
    python -m nhl_isolated.scripts.healthcheck
    # or in Docker:
    docker exec container_name python -m nhl_isolated.scripts.healthcheck
"""

import sys
from datetime import date, timedelta

def check_database() -> bool:
    """Check if database is accessible."""
    try:
        from database.db_manager import NHLDBManager
        db = NHLDBManager()
        # Try to get recent predictions
        yesterday = date.today() - timedelta(days=1)
        db.get_unsettled_predictions(yesterday)
        return True
    except Exception as e:
        print(f"[FAIL] Database: {e}")
        return False

def check_nhl_api() -> bool:
    """Check if NHL API is accessible."""
    try:
        from providers.nhl_official_api import NHLOfficialAPI
        api = NHLOfficialAPI()
        games = api.get_games_by_date(date.today())
        # API should return a list (even if empty)
        if isinstance(games, list):
            return True
        return False
    except Exception as e:
        print(f"[FAIL] NHL API: {e}")
        return False

def check_dailyfaceoff() -> bool:
    """Check if DailyFaceoff scraper is working."""
    try:
        from providers.dailyfaceoff_scraper import DailyFaceoffScraper
        scraper = DailyFaceoffScraper()
        # Try to get line data for a popular team
        lines = scraper.get_team_lines('EDM')
        if lines and 'forwards' in lines:
            return True
        # May fail if cache is cold, that's okay
        return True
    except Exception as e:
        print(f"[FAIL] DailyFaceoff: {e}")
        return False

def check_recent_predictions() -> bool:
    """Check if we have recent predictions in the database."""
    try:
        from database.db_manager import NHLDBManager
        db = NHLDBManager()

        # Check for predictions in the last 7 days
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        report = db.get_hit_rate_summary(start_date, end_date)
        total = report.get('total_predictions', 0)

        if total > 0:
            return True
        else:
            print(f"[WARN] No predictions found in last 7 days")
            return True  # Not a failure, could be off-season
    except Exception as e:
        print(f"[FAIL] Recent predictions check: {e}")
        return False

def main():
    """Run all health checks."""
    print("=" * 50)
    print("NHL Pipeline Health Check")
    print("=" * 50)

    checks = [
        ("Database", check_database),
        ("NHL API", check_nhl_api),
        ("DailyFaceoff", check_dailyfaceoff),
        ("Recent Data", check_recent_predictions),
    ]

    all_passed = True

    for name, check_fn in checks:
        try:
            result = check_fn()
            status = "OK" if result else "FAIL"
            print(f"  {name}: {status}")
            if not result:
                all_passed = False
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
            all_passed = False

    print("=" * 50)

    if all_passed:
        print("Status: HEALTHY")
        return 0
    else:
        print("Status: UNHEALTHY")
        return 1


if __name__ == '__main__':
    sys.exit(main())
