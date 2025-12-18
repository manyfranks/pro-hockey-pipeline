"""
NHL Game Totals Daily Generator

Production workflow for game-level O/U (totals) predictions:
1. Fetch today's games from Odds API
2. Fetch current game totals odds
3. Calculate expected total using GameTotalsSignal
4. Filter by edge bucket (10-15% = 87.5% hit rate validated)
5. Generate picks with thesis narrative

KEY INSIGHT: Game totals show OPPOSITE behavior to player props:
- Higher edge = BETTER outcomes (no contrarian needed!)
- 10-15% edge bucket: 87.5% hit rate (Dec 18, 2025 backtest)
- Strong UNDER signals: 64.1% hit rate

Usage:
    python -m nhl_sgp_engine.scripts.daily_game_totals_generator
    python -m nhl_sgp_engine.scripts.daily_game_totals_generator --date 2025-12-18
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.signals.game_totals_signal import GameTotalsSignal
from nhl_sgp_engine.signals.base import PropContext
from nhl_sgp_engine.providers.nhl_data_provider import normalize_team


# =============================================================================
# Production Filters (validated by Dec 18, 2025 backtest - 364 game totals)
# KEY INSIGHT: Higher model edge = BETTER outcomes (FOLLOW the model!)
# RESULTS: 87.5% hit rate at 10-15% edge, 57.0% overall
# =============================================================================

# Edge bucket filters - FOLLOW model direction (no contrarian)
MIN_EDGE_PCT = 5.0     # Minimum edge to consider
OPTIMAL_EDGE_MIN = 10.0  # Optimal bucket: 10-15% edge (87.5% hit rate!)
OPTIMAL_EDGE_MAX = 15.0

# Signal strength filters
STRONG_UNDER_THRESHOLD = -0.3  # Strong UNDER signals hit 64.1%
STRONG_OVER_THRESHOLD = 0.3    # Strong OVER signals hit 59.3%


@dataclass
class GameTotalPick:
    """A game total pick for today."""
    event_id: str
    game_date: str
    home_team: str
    away_team: str
    matchup: str
    line: float
    over_odds: int
    under_odds: int
    bookmaker: str
    # Signal results
    expected_total: float
    signal_strength: float
    signal_confidence: float
    direction: str  # 'over' or 'under'
    edge_pct: float
    # Quality indicators
    in_optimal_bucket: bool = False
    is_strong_signal: bool = False


class GameTotalsGenerator:
    """Generate game total (O/U) picks for NHL games."""

    def __init__(self):
        self.odds_client = OddsAPIClient()
        self.signal = GameTotalsSignal()

    def _american_to_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def fetch_todays_game_totals(self, game_date: date) -> List[GameTotalPick]:
        """Fetch game totals for today's games."""
        print(f"\n[Game Totals] Fetching totals for {game_date}...")

        try:
            events = self.odds_client.get_current_events()
        except Exception as e:
            print(f"[Game Totals] Error fetching events: {e}")
            return []

        # Filter to today's games (convert UTC to ET)
        et_tz = ZoneInfo('America/New_York')
        todays_events = []
        for event in events:
            commence_time = event.get('commence_time', '')
            if commence_time:
                utc_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                et_dt = utc_dt.astimezone(et_tz)
                if et_dt.date() == game_date:
                    todays_events.append(event)

        print(f"[Game Totals] Found {len(todays_events)} games today")

        if not todays_events:
            return []

        picks = []

        for event in todays_events:
            event_id = event.get('id', '')
            home_team = event.get('home_team', '')
            away_team = event.get('away_team', '')
            matchup = f"{normalize_team(away_team)}@{normalize_team(home_team)}"

            try:
                # Get game-level odds for this event
                totals_data = self.odds_client.get_current_game_odds(
                    event_id=event_id,
                    markets=['totals'],
                )
            except Exception as e:
                print(f"[Game Totals] Error fetching totals for {matchup}: {e}")
                continue

            # Parse totals
            game_totals = self.odds_client.parse_game_totals(totals_data)

            for total in game_totals:
                pick = GameTotalPick(
                    event_id=event_id,
                    game_date=game_date.isoformat(),
                    home_team=total['home_team'],
                    away_team=total['away_team'],
                    matchup=matchup,
                    line=total['line'],
                    over_odds=total['over_price'],
                    under_odds=total['under_price'],
                    bookmaker=total['bookmaker'],
                    expected_total=0.0,
                    signal_strength=0.0,
                    signal_confidence=0.0,
                    direction='',
                    edge_pct=0.0,
                )
                picks.append(pick)
                break  # One per game (prefer first/DraftKings)

        print(f"[Game Totals] Found {len(picks)} game totals")
        return picks

    def calculate_signals(self, picks: List[GameTotalPick]) -> List[GameTotalPick]:
        """Calculate signals for each game total."""
        print(f"\n[Game Totals] Calculating signals for {len(picks)} games...")

        for pick in picks:
            # Build context for signal
            ctx = PropContext(
                player_id=0,
                player_name='Game Total',
                team=pick.home_team,
                position='',
                stat_type='totals',
                line=pick.line,
                game_id=pick.event_id,
                game_date=pick.game_date,
                opponent=pick.away_team,
                is_home=True,
            )

            # Calculate signal
            result = self.signal.calculate(
                player_id=0,
                player_name='Game Total',
                stat_type='totals',
                line=pick.line,
                game_context=ctx,
            )

            pick.expected_total = result.raw_data.get('expected_total', 0)
            pick.signal_strength = result.strength
            pick.signal_confidence = result.confidence

            # Determine direction based on signal (NO CONTRARIAN - follow model!)
            if result.strength > 0.1:
                pick.direction = 'over'
            elif result.strength < -0.1:
                pick.direction = 'under'
            else:
                pick.direction = 'over' if result.strength >= 0 else 'under'

            # Calculate edge
            over_prob = self._american_to_prob(pick.over_odds)
            under_prob = self._american_to_prob(pick.under_odds)

            # Model probability based on signal
            model_prob_over = 0.5 + (result.strength * 0.25)
            model_prob_under = 1 - model_prob_over

            if pick.direction == 'over':
                pick.edge_pct = (model_prob_over - over_prob) * 100
            else:
                pick.edge_pct = (model_prob_under - under_prob) * 100

            # Mark quality indicators
            pick.in_optimal_bucket = OPTIMAL_EDGE_MIN <= pick.edge_pct <= OPTIMAL_EDGE_MAX
            pick.is_strong_signal = (
                pick.signal_strength <= STRONG_UNDER_THRESHOLD or
                pick.signal_strength >= STRONG_OVER_THRESHOLD
            )

        return picks

    def filter_picks(self, picks: List[GameTotalPick]) -> List[GameTotalPick]:
        """Filter to actionable picks."""
        actionable = []

        for pick in picks:
            # Minimum edge threshold
            if pick.edge_pct < MIN_EDGE_PCT:
                continue

            actionable.append(pick)

        # Sort by edge (highest first - FOLLOW the model!)
        actionable.sort(key=lambda x: x.edge_pct, reverse=True)

        return actionable

    def run(self, game_date: date = None, output_file: str = None) -> Dict:
        """Run the game totals generation pipeline."""
        game_date = game_date or date.today()

        print("=" * 70)
        print(f"NHL GAME TOTALS GENERATOR - {game_date}")
        print("=" * 70)
        print("KEY: Game totals FOLLOW model direction (no contrarian)")
        print("     10-15% edge = 87.5% hit rate (validated Dec 18, 2025)")

        # Check API budget
        status = self.odds_client.test_connection()
        print(f"\nOdds API remaining: {status.get('requests_remaining')}")

        # Fetch today's game totals
        picks = self.fetch_todays_game_totals(game_date)
        if not picks:
            print("[Game Totals] No games found for today")
            return {'picks': 0, 'game_date': str(game_date)}

        # Calculate signals
        picks = self.calculate_signals(picks)

        # Filter to actionable
        actionable = self.filter_picks(picks)

        # Display picks
        print(f"\n{'='*70}")
        print("GAME TOTAL PICKS")
        print(f"{'='*70}")

        optimal_picks = [p for p in actionable if p.in_optimal_bucket]
        strong_picks = [p for p in actionable if p.is_strong_signal]

        if optimal_picks:
            print(f"\n--- OPTIMAL BUCKET (10-15% edge) - 87.5% hit rate ---")
            for pick in optimal_picks:
                direction_char = 'O' if pick.direction == 'over' else 'U'
                print(f"  {pick.matchup}: {direction_char}{pick.line} ({pick.over_odds if pick.direction == 'over' else pick.under_odds:+d})")
                print(f"    Expected: {pick.expected_total:.1f} | Edge: {pick.edge_pct:.1f}% | Strength: {pick.signal_strength:.2f}")

        if strong_picks:
            print(f"\n--- STRONG SIGNALS (|strength| > 0.3) ---")
            for pick in strong_picks:
                if pick not in optimal_picks:
                    direction_char = 'O' if pick.direction == 'over' else 'U'
                    print(f"  {pick.matchup}: {direction_char}{pick.line} ({pick.over_odds if pick.direction == 'over' else pick.under_odds:+d})")
                    print(f"    Expected: {pick.expected_total:.1f} | Edge: {pick.edge_pct:.1f}% | Strength: {pick.signal_strength:.2f}")

        other_picks = [p for p in actionable if p not in optimal_picks and p not in strong_picks]
        if other_picks:
            print(f"\n--- OTHER ACTIONABLE ({MIN_EDGE_PCT}%+ edge) ---")
            for pick in other_picks:
                direction_char = 'O' if pick.direction == 'over' else 'U'
                print(f"  {pick.matchup}: {direction_char}{pick.line} ({pick.over_odds if pick.direction == 'over' else pick.under_odds:+d})")
                print(f"    Expected: {pick.expected_total:.1f} | Edge: {pick.edge_pct:.1f}% | Strength: {pick.signal_strength:.2f}")

        # Summary
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"Total games: {len(picks)}")
        print(f"Actionable picks: {len(actionable)}")
        print(f"Optimal bucket (10-15%): {len(optimal_picks)}")
        print(f"Strong signals: {len(strong_picks)}")

        # Direction breakdown
        overs = [p for p in actionable if p.direction == 'over']
        unders = [p for p in actionable if p.direction == 'under']
        print(f"\nBy direction: {len(overs)} OVER, {len(unders)} UNDER")

        # Save results
        if output_file or actionable:
            output_dir = Path(__file__).parent.parent / 'data' / 'game_totals_daily'
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = output_dir / f"game_totals_{game_date}_{timestamp}.json"

            with open(output_path, 'w') as f:
                json.dump({
                    'game_date': str(game_date),
                    'generated_at': datetime.now().isoformat(),
                    'picks': [asdict(p) for p in actionable],
                    'summary': {
                        'total_games': len(picks),
                        'actionable': len(actionable),
                        'optimal_bucket': len(optimal_picks),
                        'strong_signals': len(strong_picks),
                    }
                }, f, indent=2, default=str)

            print(f"\nResults saved to: {output_path}")

        print("=" * 70)

        return {
            'game_date': str(game_date),
            'picks': len(actionable),
            'optimal_bucket': len(optimal_picks),
            'strong_signals': len(strong_picks),
        }


def main():
    parser = argparse.ArgumentParser(description='Generate NHL game total picks')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD), default: today')
    args = parser.parse_args()

    game_date = date.fromisoformat(args.date) if args.date else date.today()

    generator = GameTotalsGenerator()
    result = generator.run(game_date=game_date)

    print(f"\n[Game Totals] Complete: {result['picks']} picks for {result['game_date']}")
    return result


if __name__ == '__main__':
    main()
