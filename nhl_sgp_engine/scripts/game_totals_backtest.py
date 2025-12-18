"""
Game Totals Backtest

Backtest game total (O/U) predictions against historical results.
Uses GameTotalsSignal to calculate expected totals and compares to actual scores.

Usage:
    python -m nhl_sgp_engine.scripts.game_totals_backtest --start 2025-11-01 --end 2025-12-15
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.signals.game_totals_signal import GameTotalsSignal
from nhl_sgp_engine.signals.base import PropContext
from providers.nhl_official_api import NHLOfficialAPI


@dataclass
class GameTotalProp:
    """A game total prop for backtesting."""
    event_id: str
    game_date: str
    home_team: str
    away_team: str
    line: float
    over_odds: int
    under_odds: int
    bookmaker: str
    # Signal results
    expected_total: float = 0.0
    signal_strength: float = 0.0
    signal_confidence: float = 0.0
    direction: str = ''  # 'over' or 'under'
    edge_pct: float = 0.0
    # Settlement
    actual_total: Optional[int] = None
    hit: Optional[bool] = None
    settled: bool = False


class GameTotalsBacktest:
    """Backtest engine for game totals."""

    def __init__(self, use_cache: bool = True, contrarian_threshold: float = None):
        self.odds_client = OddsAPIClient()
        self.nhl_api = NHLOfficialAPI()
        self.signal = GameTotalsSignal()
        self.use_cache = use_cache
        self.contrarian_threshold = contrarian_threshold

    def fetch_historical_totals(
        self,
        start_date: date,
        end_date: date,
    ) -> List[GameTotalProp]:
        """Fetch historical game totals for date range."""
        props = []
        current = start_date

        while current <= end_date:
            date_str = current.strftime('%Y-%m-%d')
            print(f"  Fetching {date_str}...", end=' ')

            try:
                # Get historical events for this date
                events = self.odds_client.get_historical_events(date_str, use_cache=self.use_cache)

                day_props = 0
                for event in events:
                    event_id = event.get('id', '')
                    if not event_id:
                        continue

                    # Get historical game odds
                    try:
                        odds_data = self.odds_client.get_historical_game_odds(
                            event_id=event_id,
                            date_str=date_str,
                            markets=['totals'],
                            use_cache=self.use_cache,
                        )
                    except Exception as e:
                        continue

                    # Parse totals
                    totals = self.odds_client.parse_game_totals(odds_data.get('data', odds_data))

                    for total in totals:
                        prop = GameTotalProp(
                            event_id=event_id,
                            game_date=date_str,
                            home_team=total['home_team'],
                            away_team=total['away_team'],
                            line=total['line'],
                            over_odds=total['over_price'],
                            under_odds=total['under_price'],
                            bookmaker=total['bookmaker'],
                        )
                        props.append(prop)
                        day_props += 1

                print(f"{day_props} totals")

            except Exception as e:
                print(f"Error: {e}")

            current += timedelta(days=1)

        return props

    def calculate_signals(self, props: List[GameTotalProp]) -> List[GameTotalProp]:
        """Calculate signal for each game total prop."""
        print(f"\nCalculating signals for {len(props)} game totals...")

        for i, prop in enumerate(props):
            if i % 50 == 0:
                print(f"  Processing {i}/{len(props)}...")

            # Build context for signal
            ctx = PropContext(
                player_id=0,
                player_name='Game Total',
                team=prop.home_team,
                position='',
                stat_type='totals',
                line=prop.line,
                game_id=prop.event_id,
                game_date=prop.game_date,
                opponent=prop.away_team,
                is_home=True,
            )

            # Calculate signal
            result = self.signal.calculate(
                player_id=0,
                player_name='Game Total',
                stat_type='totals',
                line=prop.line,
                game_context=ctx,
            )

            prop.expected_total = result.raw_data.get('expected_total', 0)
            prop.signal_strength = result.strength
            prop.signal_confidence = result.confidence

            # Determine direction based on signal
            if result.strength > 0.1:
                prop.direction = 'over'
            elif result.strength < -0.1:
                prop.direction = 'under'
            else:
                prop.direction = 'over' if result.strength >= 0 else 'under'

            # Calculate edge
            over_prob = self._american_to_prob(prop.over_odds)
            under_prob = self._american_to_prob(prop.under_odds)

            # Model probability based on signal
            model_prob_over = 0.5 + (result.strength * 0.25)  # Scale signal to prob adjustment
            model_prob_under = 1 - model_prob_over

            if prop.direction == 'over':
                prop.edge_pct = (model_prob_over - over_prob) * 100
            else:
                prop.edge_pct = (model_prob_under - under_prob) * 100

            # Apply contrarian logic if threshold set
            if self.contrarian_threshold and abs(prop.edge_pct) > self.contrarian_threshold:
                # Flip direction
                prop.direction = 'under' if prop.direction == 'over' else 'over'

        return props

    def settle_props(self, props: List[GameTotalProp]) -> List[GameTotalProp]:
        """Settle props against actual game scores."""
        print(f"\nSettling {len(props)} game totals against box scores...")

        # Import team normalization
        from nhl_sgp_engine.providers.nhl_data_provider import normalize_team

        settled_count = 0
        for prop in props:
            try:
                # Get box score for this game
                games = self.nhl_api.get_games_by_date(date.fromisoformat(prop.game_date))

                # Normalize prop team names to abbreviations
                prop_home = normalize_team(prop.home_team)
                prop_away = normalize_team(prop.away_team)

                for game in games:
                    # Game data has teams as abbreviations directly
                    home = game.get('home_team', '')
                    away = game.get('away_team', '')

                    # Match game
                    if self._teams_match(home, away, prop_home, prop_away):
                        home_score = game.get('home_score', 0)
                        away_score = game.get('away_score', 0)
                        actual_total = home_score + away_score

                        prop.actual_total = actual_total
                        prop.settled = True

                        # Determine if hit
                        if prop.direction == 'over':
                            prop.hit = actual_total > prop.line
                        else:
                            prop.hit = actual_total < prop.line

                        settled_count += 1
                        break

            except Exception as e:
                continue

        print(f"  Settled {settled_count}/{len(props)} game totals")
        return props

    def _teams_match(self, home1: str, away1: str, home2: str, away2: str) -> bool:
        """Check if team pairs match."""
        h1, a1 = home1.upper()[:3], away1.upper()[:3]
        h2, a2 = home2.upper()[:3], away2.upper()[:3]
        return (h1 == h2 and a1 == a2) or (h1 in h2 or h2 in h1) and (a1 in a2 or a2 in a1)

    def _american_to_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def generate_summary(self, props: List[GameTotalProp]) -> Dict:
        """Generate backtest summary."""
        settled = [p for p in props if p.settled]
        hits = [p for p in settled if p.hit]

        # By direction
        overs = [p for p in settled if p.direction == 'over']
        unders = [p for p in settled if p.direction == 'under']
        over_hits = [p for p in overs if p.hit]
        under_hits = [p for p in unders if p.hit]

        # By edge bucket
        def bucket_stats(bucket_props):
            bucket_hits = [p for p in bucket_props if p.hit]
            return {
                'total': len(bucket_props),
                'hits': len(bucket_hits),
                'hit_rate': len(bucket_hits) / len(bucket_props) * 100 if bucket_props else 0,
            }

        negative_edge = [p for p in settled if p.edge_pct < 0]
        edge_0_5 = [p for p in settled if 0 <= p.edge_pct < 5]
        edge_5_10 = [p for p in settled if 5 <= p.edge_pct < 10]
        edge_10_15 = [p for p in settled if 10 <= p.edge_pct < 15]
        edge_15_plus = [p for p in settled if p.edge_pct >= 15]

        # By signal strength
        strong_over = [p for p in settled if p.signal_strength > 0.3]
        strong_under = [p for p in settled if p.signal_strength < -0.3]

        summary = {
            'total_props': len(props),
            'settled_props': len(settled),
            'hit_count': len(hits),
            'hit_rate': len(hits) / len(settled) * 100 if settled else 0,
            'by_direction': {
                'over': {
                    'total': len(overs),
                    'hits': len(over_hits),
                    'hit_rate': len(over_hits) / len(overs) * 100 if overs else 0,
                },
                'under': {
                    'total': len(unders),
                    'hits': len(under_hits),
                    'hit_rate': len(under_hits) / len(unders) * 100 if unders else 0,
                },
            },
            'by_edge_bucket': {
                'negative': bucket_stats(negative_edge),
                '0-5%': bucket_stats(edge_0_5),
                '5-10%': bucket_stats(edge_5_10),
                '10-15%': bucket_stats(edge_10_15),
                '15%+': bucket_stats(edge_15_plus),
            },
            'by_signal_strength': {
                'strong_over': bucket_stats(strong_over),
                'strong_under': bucket_stats(strong_under),
            },
            'contrarian_threshold': self.contrarian_threshold,
        }

        return summary

    def run(self, start_date: date, end_date: date) -> Dict:
        """Run full backtest pipeline."""
        print("=" * 70)
        print("GAME TOTALS BACKTEST")
        print("=" * 70)
        print(f"Date range: {start_date} to {end_date}")
        if self.contrarian_threshold:
            print(f"Contrarian mode: Fade when edge > {self.contrarian_threshold}%")

        # Check API budget
        status = self.odds_client.test_connection()
        print(f"Odds API remaining: {status.get('requests_remaining')}")

        # Fetch historical totals
        print("\n" + "-" * 50)
        print("FETCHING HISTORICAL GAME TOTALS...")
        print("-" * 50)
        props = self.fetch_historical_totals(start_date, end_date)
        print(f"\nTotal game totals fetched: {len(props)}")

        if not props:
            print("No game totals found!")
            return {}

        # Calculate signals
        print("\n" + "-" * 50)
        print("CALCULATING SIGNALS...")
        print("-" * 50)
        props = self.calculate_signals(props)

        # Settle against box scores
        print("\n" + "-" * 50)
        print("SETTLING AGAINST BOX SCORES...")
        print("-" * 50)
        props = self.settle_props(props)

        # Generate summary
        summary = self.generate_summary(props)

        # Print results
        print("\n" + "=" * 70)
        print("BACKTEST RESULTS")
        print("=" * 70)
        print(f"\nTotal game totals: {summary['total_props']}")
        print(f"Settled: {summary['settled_props']}")
        print(f"Overall hit rate: {summary['hit_rate']:.1f}%")

        print(f"\n--- By Direction ---")
        for direction, stats in summary['by_direction'].items():
            print(f"  {direction.upper()}: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total']})")

        print(f"\n--- By Edge Bucket ---")
        for bucket, stats in summary['by_edge_bucket'].items():
            if stats['total'] > 0:
                print(f"  {bucket}: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total']})")

        print(f"\n--- By Signal Strength ---")
        for strength, stats in summary['by_signal_strength'].items():
            if stats['total'] > 0:
                print(f"  {strength}: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total']})")

        # Save results
        output_dir = Path(__file__).parent.parent / 'data' / 'game_totals_backtest'
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"game_totals_{start_date}_{end_date}_{timestamp}.json"

        with open(output_file, 'w') as f:
            json.dump({
                'summary': summary,
                'props': [asdict(p) for p in props],
            }, f, indent=2, default=str)

        print(f"\nResults saved to: {output_file}")
        print("=" * 70)

        return summary


def main():
    parser = argparse.ArgumentParser(description='Backtest game totals')
    parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--contrarian', type=float, default=None, help='Contrarian threshold')
    parser.add_argument('--no-cache', action='store_true', help='Disable cache')
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    backtest = GameTotalsBacktest(
        use_cache=not args.no_cache,
        contrarian_threshold=args.contrarian,
    )
    backtest.run(start, end)


if __name__ == '__main__':
    main()
