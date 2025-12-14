"""
Daily Prediction Pipeline for NHL SGP Engine

Production workflow:
1. Fetch today's games from Odds API
2. Fetch current odds for player props
3. Calculate edge using NHL API data
4. Filter to actionable props (10%+ edge, validated markets)
5. Upsert predictions to database

Usage:
    python -m nhl_sgp_engine.scripts.daily_predictions
    python -m nhl_sgp_engine.scripts.daily_predictions --date 2025-12-15
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from datetime import date, datetime
from typing import Dict, List, Optional
from decimal import Decimal

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.providers.context_builder import PropContextBuilder
from nhl_sgp_engine.providers.nhl_data_provider import NHLDataProvider, normalize_team
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.markets import MARKET_TO_STAT_TYPE


# =============================================================================
# Production Filters (based on backtest validation)
# =============================================================================

# Markets validated with positive hit rate correlation
VALIDATED_MARKETS = [
    'player_points',        # 46.0% hit rate, 10-15% edge = 49.6%
    'player_shots_on_goal', # 50.1% hit rate
    'player_blocked_shots', # 44.4% hit rate
]

# Minimum edge threshold (10-15% bucket showed 49.6% hit rate)
MIN_EDGE_PCT = 10.0

# Maximum edge (>15% showed slight drop, might be overfitting)
MAX_EDGE_PCT = 25.0


class DailyPredictionPipeline:
    """Generate daily predictions for NHL player props."""

    def __init__(self):
        self.odds_client = OddsAPIClient()
        self.context_builder = PropContextBuilder()
        self.nhl_provider = NHLDataProvider()
        self.edge_calculator = EdgeCalculator()
        self.db = NHLSGPDBManager()

        self.predictions: List[Dict] = []

    def _american_to_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def calculate_edge(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        over_odds: int,
        game_date: date,
        team: str = None,
        opponent: str = None,
    ) -> Optional[Dict]:
        """
        Calculate edge for a player prop.

        Returns dict with edge_pct, model_prob, context or None if no data.
        """
        use_pipeline = stat_type in ['points', 'assists', 'goals']

        try:
            ctx = self.context_builder.build_context(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                game_date=game_date,
                team=team,
                opponent=opponent,
                use_pipeline=use_pipeline,
            )
        except Exception as e:
            return None

        if not ctx or not ctx.has_nhl_api_data:
            return None

        try:
            under_odds = -over_odds if over_odds > 0 else -over_odds
            edge_result = self.edge_calculator.calculate_edge(ctx, over_odds, under_odds)

            # Calculate OVER edge specifically
            over_prob = self._american_to_prob(over_odds)
            model_prob_over = edge_result.model_probability if edge_result.direction == 'over' else 1 - edge_result.model_probability
            over_edge = (model_prob_over - over_prob) * 100

            return {
                'edge_pct': over_edge,
                'model_probability': model_prob_over,
                'market_probability': over_prob,
                'confidence': edge_result.confidence,
                'direction': 'over' if over_edge > 0 else 'under',
                'season_avg': ctx.season_avg,
                'recent_avg': ctx.recent_avg if hasattr(ctx, 'recent_avg') else None,
                'primary_reason': edge_result.primary_reason,
                'signals': edge_result.signals,
            }
        except Exception as e:
            return None

    def fetch_todays_props(self, game_date: date) -> List[Dict]:
        """Fetch props for today's games from Odds API."""
        print(f"\n[Pipeline] Fetching props for {game_date}...")

        # First get list of events
        try:
            events = self.odds_client.get_current_events()
        except Exception as e:
            print(f"[Pipeline] Error fetching events: {e}")
            return []

        # Filter to today's games
        todays_events = []
        for event in events:
            commence_time = event.get('commence_time', '')
            if commence_time:
                game_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                if game_dt.date() == game_date:
                    todays_events.append(event)

        print(f"[Pipeline] Found {len(todays_events)} games today")

        if not todays_events:
            return []

        props = []
        for event in todays_events:
            event_id = event.get('id')
            home = event.get('home_team', '')
            away = event.get('away_team', '')
            matchup = f"{away}@{home}"

            # Fetch player props for this event
            try:
                event_odds = self.odds_client.get_event_odds(
                    event_id=event_id,
                    markets=VALIDATED_MARKETS,
                )
            except Exception as e:
                print(f"[Pipeline] Error fetching odds for {matchup}: {e}")
                continue

            for bm in event_odds.get('bookmakers', []):
                if bm.get('key') != 'draftkings':
                    continue

                for market in bm.get('markets', []):
                    market_key = market.get('key')

                    if market_key not in VALIDATED_MARKETS:
                        continue

                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description', '')
                        direction = outcome.get('name', '').lower()
                        odds = outcome.get('price', 0)
                        line = outcome.get('point', 0.5)

                        if not player_name or direction != 'over':
                            continue

                        props.append({
                            'event_id': event_id,
                            'matchup': matchup,
                            'home_team': home,
                            'away_team': away,
                            'player_name': player_name,
                            'market_key': market_key,
                            'stat_type': MARKET_TO_STAT_TYPE.get(market_key, market_key.replace('player_', '')),
                            'line': line,
                            'odds': odds,
                        })

        print(f"[Pipeline] Found {len(props)} props across {len(todays_events)} games")
        return props

    def process_props(self, props: List[Dict], game_date: date) -> List[Dict]:
        """Calculate edge for each prop and filter to actionable."""
        print(f"\n[Pipeline] Processing {len(props)} props...")

        actionable = []

        for i, prop in enumerate(props):
            if i % 50 == 0:
                print(f"  Progress: {i}/{len(props)}")

            # Try both teams to find player
            edge_data = self.calculate_edge(
                player_name=prop['player_name'],
                stat_type=prop['stat_type'],
                line=prop['line'],
                over_odds=prop['odds'],
                game_date=game_date,
                team=prop['home_team'],
                opponent=prop['away_team'],
            )

            if not edge_data:
                edge_data = self.calculate_edge(
                    player_name=prop['player_name'],
                    stat_type=prop['stat_type'],
                    line=prop['line'],
                    over_odds=prop['odds'],
                    game_date=game_date,
                    team=prop['away_team'],
                    opponent=prop['home_team'],
                )

            if not edge_data:
                continue

            edge_pct = edge_data['edge_pct']

            # Apply production filters
            if edge_pct < MIN_EDGE_PCT or edge_pct > MAX_EDGE_PCT:
                continue

            # Build prediction record
            prediction = {
                'game_date': game_date,
                'event_id': prop['event_id'],
                'matchup': prop['matchup'],
                'home_team': normalize_team(prop['home_team']),
                'away_team': normalize_team(prop['away_team']),
                'player_name': prop['player_name'],
                'market_key': prop['market_key'],
                'stat_type': prop['stat_type'],
                'line': Decimal(str(prop['line'])),
                'direction': 'over',
                'odds': prop['odds'],
                'edge_pct': Decimal(str(round(edge_pct, 2))),
                'model_probability': Decimal(str(round(edge_data['model_probability'], 4))),
                'market_probability': Decimal(str(round(edge_data['market_probability'], 4))),
                'confidence': Decimal(str(round(edge_data['confidence'], 2))),
                'season_avg': Decimal(str(round(edge_data['season_avg'], 2))) if edge_data['season_avg'] else None,
                'recent_avg': Decimal(str(round(edge_data['recent_avg'], 2))) if edge_data.get('recent_avg') else None,
                'primary_reason': edge_data['primary_reason'],
                'signals': edge_data['signals'],
            }

            actionable.append(prediction)

        print(f"[Pipeline] Found {len(actionable)} actionable predictions (>={MIN_EDGE_PCT}% edge)")
        return actionable

    def run(self, game_date: date = None, dry_run: bool = False) -> Dict:
        """
        Run the daily prediction pipeline.

        Args:
            game_date: Date to generate predictions for (default: today)
            dry_run: If True, don't write to database

        Returns:
            Summary dict
        """
        game_date = game_date or date.today()

        print("=" * 70)
        print(f"NHL SGP DAILY PREDICTIONS - {game_date}")
        print("=" * 70)

        # Check API budget
        status = self.odds_client.test_connection()
        print(f"\nOdds API remaining: {status.get('requests_remaining')}")

        # Fetch props
        props = self.fetch_todays_props(game_date)
        if not props:
            print("[Pipeline] No props found for today")
            return {'predictions': 0, 'game_date': str(game_date)}

        # Process and filter
        predictions = self.process_props(props, game_date)

        if not predictions:
            print("[Pipeline] No actionable predictions found")
            return {'predictions': 0, 'game_date': str(game_date)}

        # Sort by edge
        predictions.sort(key=lambda x: float(x['edge_pct']), reverse=True)

        # Display top predictions
        print(f"\n{'='*70}")
        print("TOP PREDICTIONS")
        print(f"{'='*70}")
        print(f"{'Player':<25} | {'Market':<15} | {'Line':>5} | {'Odds':>5} | {'Edge':>6}")
        print("-" * 70)
        for pred in predictions[:15]:
            print(f"{pred['player_name']:<25} | {pred['stat_type']:<15} | {pred['line']:>5} | {pred['odds']:>5} | {pred['edge_pct']:>5.1f}%")

        # Save to database
        if not dry_run:
            print(f"\n[Pipeline] Saving {len(predictions)} predictions to database...")
            self.db.create_tables()
            count = self.db.bulk_upsert_predictions(predictions)
            print(f"[Pipeline] Saved {count} predictions")
        else:
            print(f"\n[Pipeline] DRY RUN - would save {len(predictions)} predictions")

        # Summary by market
        by_market = {}
        for pred in predictions:
            mk = pred['market_key']
            if mk not in by_market:
                by_market[mk] = {'count': 0, 'avg_edge': 0}
            by_market[mk]['count'] += 1
            by_market[mk]['avg_edge'] += float(pred['edge_pct'])

        for mk in by_market:
            by_market[mk]['avg_edge'] /= by_market[mk]['count']

        print(f"\n{'='*70}")
        print("SUMMARY BY MARKET")
        print(f"{'='*70}")
        for mk, stats in sorted(by_market.items(), key=lambda x: x[1]['count'], reverse=True):
            print(f"  {mk}: {stats['count']} predictions, {stats['avg_edge']:.1f}% avg edge")

        return {
            'game_date': str(game_date),
            'predictions': len(predictions),
            'by_market': by_market,
        }


def main():
    parser = argparse.ArgumentParser(description='Generate daily NHL prop predictions')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD), default: today')
    parser.add_argument('--dry-run', action='store_true', help='Do not write to database')
    args = parser.parse_args()

    game_date = date.fromisoformat(args.date) if args.date else date.today()

    pipeline = DailyPredictionPipeline()
    result = pipeline.run(game_date=game_date, dry_run=args.dry_run)

    print(f"\n[Pipeline] Complete: {result['predictions']} predictions for {result['game_date']}")
    return result


if __name__ == '__main__':
    main()
