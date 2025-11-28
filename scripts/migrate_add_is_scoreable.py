#!/usr/bin/env python3
"""
Migration script to add is_scoreable column and backfill existing records.

Run this once after deploying the code changes:
    python scripts/migrate_add_is_scoreable.py

The is_scoreable flag gates which predictions count toward hit rate:
- Criteria: (line_number <= 3 OR pp_unit >= 1) AND final_score >= 55
- This filters to "Core" players (Top 3 lines OR Power Play) with meaningful scores
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from database.db_manager import NHLDBManager
from sqlalchemy import text


def migrate():
    """Add is_scoreable column and backfill existing data."""
    db = NHLDBManager()

    with db.Session() as session:
        # Step 1: Add column if it doesn't exist
        print("[Migration] Checking if is_scoreable column exists...")
        check_stmt = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'nhl_daily_predictions'
            AND column_name = 'is_scoreable'
        """)
        result = session.execute(check_stmt).fetchone()

        if not result:
            print("[Migration] Adding is_scoreable column...")
            add_col_stmt = text("""
                ALTER TABLE nhl_daily_predictions
                ADD COLUMN is_scoreable BOOLEAN DEFAULT FALSE
            """)
            session.execute(add_col_stmt)
            session.commit()
            print("[Migration] Column added.")
        else:
            print("[Migration] Column already exists.")

        # Step 2: Backfill is_scoreable for all existing records
        print("[Migration] Backfilling is_scoreable values...")
        print("           Criteria: (line_number <= 3 OR pp_unit >= 1) AND final_score >= 55")

        backfill_stmt = text("""
            UPDATE nhl_daily_predictions
            SET is_scoreable = (
                (line_number <= 3 OR pp_unit >= 1)
                AND final_score >= 55
            )
            WHERE is_scoreable IS NULL OR is_scoreable = FALSE
        """)
        result = session.execute(backfill_stmt)
        session.commit()
        print(f"[Migration] Backfilled {result.rowcount} records.")

        # Step 3: Show summary stats
        print("\n[Migration] Summary:")
        summary_stmt = text("""
            SELECT
                COUNT(*) as total_predictions,
                SUM(CASE WHEN is_scoreable = TRUE THEN 1 ELSE 0 END) as scoreable,
                SUM(CASE WHEN is_scoreable = FALSE OR is_scoreable IS NULL THEN 1 ELSE 0 END) as not_scoreable,
                ROUND(
                    SUM(CASE WHEN is_scoreable = TRUE THEN 1 ELSE 0 END)::numeric /
                    COUNT(*) * 100, 1
                ) as scoreable_pct
            FROM nhl_daily_predictions
        """)
        stats = session.execute(summary_stmt).fetchone()

        print(f"           Total predictions: {stats[0]}")
        print(f"           Scoreable (gated): {stats[1]} ({stats[3]}%)")
        print(f"           Not scoreable:     {stats[2]}")

        # Step 4: Show hit rate comparison
        print("\n[Migration] Hit Rate Comparison:")

        comparison_stmt = text("""
            SELECT
                'All Predictions' as scope,
                COUNT(*) as total,
                SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END) as hits,
                ROUND(
                    SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END)::numeric /
                    NULLIF(SUM(CASE WHEN point_outcome IN (0, 1) THEN 1 ELSE 0 END), 0) * 100, 1
                ) as hit_rate
            FROM nhl_daily_predictions
            WHERE point_outcome IS NOT NULL

            UNION ALL

            SELECT
                'Scoreable Only' as scope,
                COUNT(*) as total,
                SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END) as hits,
                ROUND(
                    SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END)::numeric /
                    NULLIF(SUM(CASE WHEN point_outcome IN (0, 1) THEN 1 ELSE 0 END), 0) * 100, 1
                ) as hit_rate
            FROM nhl_daily_predictions
            WHERE point_outcome IS NOT NULL AND is_scoreable = TRUE
        """)

        for row in session.execute(comparison_stmt).fetchall():
            print(f"           {row[0]:20} | {row[1]:>6} settled | {row[2]:>5} hits | {row[3]:>5}% hit rate")

    print("\n[Migration] Complete!")


if __name__ == '__main__':
    migrate()
