#!/usr/bin/env python3
# nhl_isolated/scripts/daily_orchestrator.py
"""
NHL Daily Pipeline Orchestrator

Runs the complete daily workflow:
1. Settlement - Settle yesterday's predictions against actual results
2. Predictions - Generate today's predictions and save to database
3. Insights - Generate rule-based and LLM-powered insights
4. SGP Parlays - Generate multi-leg same-game parlays (aligned with NFL/NCAAF)

Usage:
    # Run full pipeline for today
    python -m nhl_isolated.scripts.daily_orchestrator

    # Run for specific date
    python -m nhl_isolated.scripts.daily_orchestrator --date 2025-11-26

    # Skip LLM insights
    python -m nhl_isolated.scripts.daily_orchestrator --no-llm

    # Dry run (don't write to database)
    python -m nhl_isolated.scripts.daily_orchestrator --dry-run

    # Force refresh all data from APIs (ignore cache, overwrite existing predictions)
    python -m nhl_isolated.scripts.daily_orchestrator --force-refresh
"""

import os
import sys
import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment variables from .env.local
def load_env():
    """Load environment variables from .env.local file."""
    env_paths = [
        Path(__file__).parent.parent.parent / '.env.local',
        Path(__file__).parent.parent.parent / '.env',
        Path(__file__).parent.parent / '.env',
    ]

    for env_path in env_paths:
        if env_path.exists():
            print(f"Loading environment from: {env_path}")
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = value
            break

load_env()

from utilities.logger import get_logger
from database.db_manager import NHLDBManager

logger = get_logger('orchestrator')


class DailyOrchestrator:
    """
    Orchestrates the complete daily NHL prediction pipeline.

    Pipeline Order:
    1. Settlement (yesterday) - Must run first to update historical accuracy
    2. Predictions (today) - Generate new predictions with latest data
    3. Insights (today) - Generate insights based on new predictions
    4. SGP Parlays (today) - Generate multi-leg same-game parlays
    """

    def __init__(self, dry_run: bool = False, force_refresh: bool = False):
        self.dry_run = dry_run
        self.force_refresh = force_refresh
        self.db = NHLDBManager()
        self.results = {
            'settlement': None,
            'predictions': None,
            'insights': None,
            'llm_insights': None,
            'sgp': None,
            'errors': [],
        }

    def run_full_pipeline(
        self,
        target_date: date = None,
        include_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Run the complete daily pipeline.

        Args:
            target_date: Date to generate predictions for (default: today)
            include_llm: Whether to include LLM insights

        Returns:
            Dictionary with results from each stage
        """
        if target_date is None:
            target_date = date.today()

        yesterday = target_date - timedelta(days=1)

        print("\n" + "=" * 80)
        print("NHL DAILY PIPELINE ORCHESTRATOR")
        print("=" * 80)
        print(f"Target Date: {target_date}")
        print(f"Settlement Date: {yesterday}")
        print(f"Dry Run: {self.dry_run}")
        print(f"Force Refresh: {self.force_refresh}")
        print(f"Include LLM: {include_llm}")
        print("=" * 80 + "\n")

        # Stage 1: Settlement
        print("\n" + "-" * 80)
        print("STAGE 1: SETTLEMENT (Yesterday's Games)")
        print("-" * 80)
        self.results['settlement'] = self._run_settlement(yesterday)

        # Stage 2: Predictions
        print("\n" + "-" * 80)
        print("STAGE 2: PREDICTIONS (Today's Games)")
        print("-" * 80)
        self.results['predictions'] = self._run_predictions(target_date)

        # Stage 3: Insights
        print("\n" + "-" * 80)
        print("STAGE 3: INSIGHTS GENERATION")
        print("-" * 80)
        self.results['insights'] = self._run_insights(target_date, include_llm)

        # Stage 4: SGP Parlays
        print("\n" + "-" * 80)
        print("STAGE 4: SGP PARLAYS")
        print("-" * 80)
        self.results['sgp'] = self._run_sgp_pipeline(target_date, yesterday)

        # Final Summary
        self._print_summary()

        return self.results

    def _run_settlement(self, settlement_date: date) -> Dict[str, Any]:
        """Run settlement for yesterday's games."""
        try:
            from pipeline.settlement import SettlementPipeline

            settler = SettlementPipeline()
            result = settler.settle_date(settlement_date, dry_run=self.dry_run)

            print(f"\n[Settlement] Completed for {settlement_date}")
            print(f"  Predictions found: {result.get('predictions_found', 0)}")
            print(f"  Settled: {result.get('settled', 0)}")
            print(f"  Hit rate: {result.get('hit_rate', 0)}%")

            return {'success': True, 'result': result}

        except Exception as e:
            error_msg = f"Settlement failed: {e}"
            logger.error(error_msg)
            self.results['errors'].append(error_msg)
            return {'success': False, 'error': str(e)}

    def _run_predictions(self, prediction_date: date) -> Dict[str, Any]:
        """Run prediction pipeline for today's games."""
        try:
            from pipeline.nhl_prediction_pipeline import NHLPredictionPipeline

            pipeline = NHLPredictionPipeline()
            predictions = pipeline.generate_predictions(
                target_date=prediction_date,
                save=True,
                force_refresh=self.force_refresh
            )

            count = len(predictions) if predictions else 0
            print(f"\n[Predictions] Generated {count} predictions for {prediction_date}")

            # Save to database if not dry run
            if predictions and not self.dry_run:
                self.db.upsert_predictions(predictions, prediction_date)
                print(f"[Predictions] Saved to database")

            if predictions and count > 0:
                # Show top 5
                print("\nTop 5 Predictions:")
                for i, p in enumerate(predictions[:5], 1):
                    score = p.get('final_score', 0)
                    # Handle Decimal types
                    if hasattr(score, '__float__'):
                        score = float(score)
                    print(f"  {i}. {p['player_name']} ({p['team']}) - Score: {score:.1f}")

            return {
                'success': True,
                'count': count,
                'top_5': predictions[:5] if predictions else []
            }

        except Exception as e:
            error_msg = f"Predictions failed: {e}"
            logger.error(error_msg)
            self.results['errors'].append(error_msg)
            return {'success': False, 'error': str(e)}

    def _run_insights(self, target_date: date, include_llm: bool) -> Dict[str, Any]:
        """Generate insights for today's predictions."""
        try:
            from analytics.insights_generator import generate_insights_for_date
            from analytics.llm_insights import LLMConfig, NHLDailyReportGenerator

            # Generate rule-based insights
            print("\n[Phase 0] Generating rule-based insights...")
            rule_insights = generate_insights_for_date(target_date, include_settlement=True)

            print(f"  Total predictions analyzed: {rule_insights.total_predictions}")
            print(f"  Hot streaks found: {len(rule_insights.hot_streaks)}")
            print(f"  Parlay recommendations: {len(rule_insights.parlays)}")

            result = {
                'success': True,
                'rule_based': {
                    'total_predictions': rule_insights.total_predictions,
                    'hot_streaks': len(rule_insights.hot_streaks),
                    'parlays': len(rule_insights.parlays),
                }
            }

            # Generate LLM insights if requested
            if include_llm:
                print("\n[Phase 1] Generating LLM insights...")

                llm_config = LLMConfig(provider="openrouter")
                print(f"  Using model: {llm_config.model}")

                report_generator = NHLDailyReportGenerator(
                    db_manager=self.db,
                    llm_config=llm_config
                )

                full_report = report_generator.generate_full_report(
                    target_date=target_date,
                    include_llm=True
                )

                # Save report
                if not self.dry_run:
                    output_path = report_generator.save_report(full_report)
                    print(f"  Report saved to: {output_path}")

                # Show LLM narrative preview
                narrative = full_report.get('llm_narrative', '')
                if narrative and not narrative.startswith('**LLM Analysis Unavailable'):
                    preview = narrative[:500] + "..." if len(narrative) > 500 else narrative
                    print(f"\n[LLM Analysis Preview]\n{preview}")
                    result['llm_narrative'] = narrative
                else:
                    print("  LLM narrative unavailable or fallback used")
                    result['llm_narrative'] = None

            return result

        except Exception as e:
            error_msg = f"Insights generation failed: {e}"
            logger.error(error_msg)
            self.results['errors'].append(error_msg)
            return {'success': False, 'error': str(e)}

    def _run_sgp_pipeline(self, target_date: date, settlement_date: date) -> Dict[str, Any]:
        """
        Run SGP parlay generation and settlement.

        Stage 4 of the pipeline - generates multi-leg same-game parlays
        aligned with NFL/NCAAF SGP architecture.
        """
        try:
            from nhl_sgp_engine.scripts.daily_sgp_generator import NHLSGPGenerator
            from nhl_sgp_engine.scripts.settle_sgp_parlays import SGPParlaySettlement

            result = {
                'settlement': None,
                'generation': None,
            }

            # Step 1: Settle yesterday's parlays
            print("\n[SGP] Settling yesterday's parlays...")
            settler = SGPParlaySettlement()
            settlement_result = settler.run(game_date=settlement_date)
            result['settlement'] = settlement_result

            print(f"  Parlays settled: {settlement_result.get('settled', 0)}")
            print(f"  Win rate: {settlement_result.get('win_rate', 0):.1f}%")
            print(f"  Profit: ${settlement_result.get('profit', 0):.2f}")

            # Step 2: Generate today's parlays
            print("\n[SGP] Generating today's parlays...")
            generator = NHLSGPGenerator()
            generation_result = generator.run(game_date=target_date, dry_run=self.dry_run)
            result['generation'] = generation_result

            print(f"  Parlays generated: {generation_result.get('parlays', 0)}")
            print(f"  Total legs: {generation_result.get('total_legs', 0)}")

            return {'success': True, 'result': result}

        except Exception as e:
            error_msg = f"SGP pipeline failed: {e}"
            logger.error(error_msg)
            self.results['errors'].append(error_msg)
            return {'success': False, 'error': str(e)}

    def _print_summary(self):
        """Print final pipeline summary."""
        print("\n" + "=" * 80)
        print("PIPELINE SUMMARY")
        print("=" * 80)

        # Settlement
        settlement = self.results.get('settlement', {})
        if settlement.get('success'):
            sr = settlement.get('result', {})
            print(f"Settlement: OK - {sr.get('settled', 0)} settled, {sr.get('hit_rate', 0)}% hit rate")
        else:
            print(f"Settlement: FAILED - {settlement.get('error', 'Unknown error')}")

        # Predictions
        predictions = self.results.get('predictions', {})
        if predictions.get('success'):
            print(f"Predictions: OK - {predictions.get('count', 0)} predictions generated")
        else:
            print(f"Predictions: FAILED - {predictions.get('error', 'Unknown error')}")

        # Insights
        insights = self.results.get('insights', {})
        if insights.get('success'):
            rb = insights.get('rule_based', {})
            llm_status = "generated" if insights.get('llm_narrative') else "unavailable"
            print(f"Insights: OK - {rb.get('parlays', 0)} parlays, LLM {llm_status}")
        else:
            print(f"Insights: FAILED - {insights.get('error', 'Unknown error')}")

        # SGP Parlays
        sgp = self.results.get('sgp', {})
        if sgp.get('success'):
            sgp_result = sgp.get('result', {})
            gen = sgp_result.get('generation', {})
            settle = sgp_result.get('settlement', {})
            print(f"SGP Parlays: OK - {gen.get('parlays', 0)} generated, {settle.get('settled', 0)} settled")
        else:
            print(f"SGP Parlays: FAILED - {sgp.get('error', 'Unknown error')}")

        # Errors
        if self.results['errors']:
            print(f"\nErrors: {len(self.results['errors'])}")
            for err in self.results['errors']:
                print(f"  - {err}")

        # Overall status
        all_success = all([
            self.results.get('settlement', {}).get('success', False),
            self.results.get('predictions', {}).get('success', False),
            self.results.get('insights', {}).get('success', False),
            self.results.get('sgp', {}).get('success', False),
        ])

        print("\n" + "=" * 80)
        if all_success:
            print("PIPELINE STATUS: SUCCESS")
        else:
            print("PIPELINE STATUS: PARTIAL FAILURE")
        print("=" * 80 + "\n")


def main():
    """Main entry point for orchestrator."""
    parser = argparse.ArgumentParser(
        description="NHL Daily Pipeline Orchestrator"
    )
    parser.add_argument(
        '--date', '-d',
        type=str,
        default=None,
        help='Target date (YYYY-MM-DD format, default: today)'
    )
    parser.add_argument(
        '--no-llm',
        action='store_true',
        help='Skip LLM insights generation'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without writing to database'
    )
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help='Force refresh all data from APIs (ignore cache, overwrite existing predictions)'
    )

    args = parser.parse_args()

    # Parse date
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = date.today()

    # Run orchestrator
    orchestrator = DailyOrchestrator(
        dry_run=args.dry_run,
        force_refresh=args.force_refresh
    )
    results = orchestrator.run_full_pipeline(
        target_date=target_date,
        include_llm=not args.no_llm
    )

    # Exit with error code if pipeline failed
    if results['errors']:
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
