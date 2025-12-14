"""
Comprehensive November 2025 Backtest - ALL Markets

Tests EVERY available prop type to determine which have edge potential
when matched against NHL API data.

Markets tested:
- Game lines: h2h, spreads, totals
- Player props: points, goals, assists, SOG, saves, blocks, PP points
- Goal scorers: anytime, first, last
- Alternates: alternate spreads, totals, team totals
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient, PlayerProp
from nhl_sgp_engine.providers.context_builder import PropContextBuilder
from nhl_sgp_engine.providers.nhl_data_provider import NHLDataProvider
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.markets import MARKET_TO_STAT_TYPE


# =============================================================================
# ALL MARKETS TO TEST
# =============================================================================

# Player props - O/U format
PLAYER_OU_MARKETS = [
    'player_points',
    'player_goals',
    'player_assists',
    'player_shots_on_goal',
    'player_blocked_shots',
    'player_power_play_points',
    'player_total_saves',
]

# Goal scorer markets - Yes/No format
GOAL_SCORER_MARKETS = [
    'player_goal_scorer_anytime',
    'player_goal_scorer_first',
    'player_goal_scorer_last',
]

# Game lines - not player-specific
GAME_MARKETS = [
    'h2h',
    'spreads',
    'totals',
    'alternate_spreads',
    'alternate_totals',
    'team_totals',
    'alternate_team_totals',
]

# All player-related markets
ALL_PLAYER_MARKETS = PLAYER_OU_MARKETS + GOAL_SCORER_MARKETS

# Core game lines for backtest
CORE_GAME_MARKETS = ['h2h', 'spreads', 'totals']

# All markets combined
ALL_MARKETS = ALL_PLAYER_MARKETS + CORE_GAME_MARKETS


@dataclass
class BacktestResult:
    """Result for a single prop."""
    game_date: str
    event_id: str
    matchup: str
    player_name: str
    market_key: str
    stat_type: str
    line: float
    direction: str  # 'over' or 'under' or 'yes'
    odds: int
    implied_prob: float
    model_prob: Optional[float]
    edge_pct: Optional[float]
    has_nhl_data: bool
    has_pipeline_data: bool
    actual_result: Optional[str]  # 'hit', 'miss', or None if unsettled
    context: Dict  # Additional context for analysis


def american_to_implied_prob(american_odds: int) -> float:
    """Convert American odds to implied probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def get_november_game_dates() -> List[str]:
    """
    Get November 2025 dates that typically have games.

    Skip Mondays (usually no games) to save API calls.
    """
    dates = []
    start = date(2025, 11, 1)
    end = date(2025, 11, 30)
    current = start
    while current <= end:
        # Skip Mondays (weekday 0)
        if current.weekday() != 0:
            dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return dates


def fetch_game_results(game_date: str) -> Dict[str, Dict]:
    """
    Fetch actual game results from NHL API for settlement.

    Returns dict mapping event_id -> {player_name: {stat_type: value}}
    """
    # TODO: Implement actual result fetching from NHL API
    # For now, return empty - we'll focus on edge calculation
    return {}


class ComprehensiveBacktest:
    """Run backtest across all markets."""

    def __init__(self):
        self.odds_client = OddsAPIClient()
        self.context_builder = PropContextBuilder()
        self.nhl_provider = NHLDataProvider()
        self.edge_calculator = EdgeCalculator()

        self.results: List[BacktestResult] = []
        self.market_stats = defaultdict(lambda: {
            'total': 0,
            'with_nhl_data': 0,
            'with_pipeline_data': 0,
            'with_edge': 0,
            'avg_edge': 0.0,
            'samples': [],
        })

    def calculate_player_prop_edge(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        over_odds: int,
        game_date: str,
        team: str = None,
        opponent: str = None,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate edge for a player prop using NHL API data.

        Returns:
            (edge_pct, context_dict)
        """
        # Build context using NHL API (PRIMARY) + Pipeline (SUPPLEMENTAL)
        use_pipeline = stat_type in ['points', 'assists', 'goals']

        try:
            ctx = self.context_builder.build_context(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                game_date=date.fromisoformat(game_date),
                team=team,
                opponent=opponent,
                use_pipeline=use_pipeline,
            )
        except Exception as e:
            return None, {'error': str(e)}

        if not ctx:
            return None, {'error': 'player_not_found'}

        context = {
            'has_nhl_data': ctx.has_nhl_api_data,
            'has_pipeline_data': ctx.has_pipeline_data if hasattr(ctx, 'has_pipeline_data') else False,
            'season_avg': ctx.season_avg,
            'recent_avg': ctx.recent_avg if hasattr(ctx, 'recent_avg') else None,
            'trend_pct': ctx.trend_pct if hasattr(ctx, 'trend_pct') else None,
            'is_scoreable': ctx.is_scoreable if hasattr(ctx, 'is_scoreable') else None,
            'pipeline_rank': ctx.pipeline_rank if hasattr(ctx, 'pipeline_rank') else None,
        }

        if not ctx.has_nhl_api_data:
            return None, context

        # Calculate edge using our signal framework
        try:
            # EdgeCalculator.calculate_edge takes over_odds and under_odds
            # Estimate under_odds from over (simplified)
            under_odds = -over_odds if over_odds > 0 else -over_odds
            edge_result = self.edge_calculator.calculate_edge(ctx, over_odds, under_odds)

            # CRITICAL: For backtest, report OVER edge specifically (not best direction)
            # We're evaluating OVER props, so we need OVER edge
            over_prob = self._american_to_prob(over_odds)
            over_edge = (edge_result.model_probability - over_prob) * 100 if edge_result.direction == 'over' else ((1 - edge_result.model_probability) - over_prob) * 100

            context['model_prob_over'] = edge_result.model_probability if edge_result.direction == 'over' else 1 - edge_result.model_probability
            context['market_prob_over'] = over_prob
            context['direction_recommended'] = edge_result.direction

            return over_edge, context
        except Exception as e:
            context['edge_error'] = str(e)
            return None, context

    def _american_to_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def calculate_goal_scorer_edge(
        self,
        player_name: str,
        market_key: str,
        odds: int,
        game_date: str,
        team: str = None,
        opponent: str = None,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate edge for goal scorer props.

        Uses goals per game rate vs implied probability.
        """
        try:
            ctx = self.context_builder.build_context_nhl_only(
                player_name=player_name,
                stat_type='goals',
                line=0.5,  # Anytime = at least 1
                game_date=date.fromisoformat(game_date),
                team=team,
                opponent=opponent,
            )
        except Exception:
            return None, {'error': 'context_failed'}

        if not ctx or not ctx.has_nhl_api_data:
            return None, {'error': 'no_nhl_data'}

        context = {
            'has_nhl_data': True,
            'has_pipeline_data': False,
            'season_goals_per_game': ctx.season_avg,
            'recent_goals_per_game': ctx.recent_avg if hasattr(ctx, 'recent_avg') else None,
        }

        # Simple probability model for goal scorers
        # Use Poisson approximation: P(score) = 1 - P(0 goals) = 1 - e^(-λ)
        import math
        goals_per_game = ctx.season_avg or 0

        if goals_per_game <= 0:
            return None, context

        # Probability of scoring at least one goal
        if market_key == 'player_goal_scorer_anytime':
            model_prob = 1 - math.exp(-goals_per_game)
        elif market_key == 'player_goal_scorer_first':
            # First goal scorer is much lower probability
            # Rough estimate: goals_per_game / total_goals_per_game * time_factor
            model_prob = goals_per_game / 6.0 * 0.5  # ~6 goals per game avg
        elif market_key == 'player_goal_scorer_last':
            model_prob = goals_per_game / 6.0 * 0.5
        else:
            model_prob = goals_per_game / 3.0  # Generic

        implied_prob = american_to_implied_prob(odds)
        edge_pct = (model_prob - implied_prob) * 100

        context['model_prob'] = model_prob
        context['implied_prob'] = implied_prob

        return edge_pct, context

    def calculate_game_line_edge(
        self,
        market_key: str,
        outcome_name: str,  # Team name for h2h, 'Over'/'Under' for totals
        odds: int,
        line: float,  # For spreads/totals
        home_team: str,
        away_team: str,
        game_date: str,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate edge for game lines (moneyline, spreads, totals).

        Uses simple historical averages for estimation.
        """
        from nhl_sgp_engine.providers.nhl_data_provider import normalize_team

        context = {
            'has_nhl_data': False,
            'market_key': market_key,
            'outcome': outcome_name,
            'line': line,
        }

        home_abbrev = normalize_team(home_team)
        away_abbrev = normalize_team(away_team)

        # Get team stats (goals for/against averages)
        try:
            home_defense = self.nhl_provider.get_team_defense(home_abbrev)
            away_defense = self.nhl_provider.get_team_defense(away_abbrev)
        except Exception:
            return None, context

        if not home_defense or not away_defense:
            return None, context

        context['has_nhl_data'] = True
        context['home_team'] = home_abbrev
        context['away_team'] = away_abbrev

        # Simple model based on goals for/against
        home_gf = home_defense.get('goals_for_per_game', 3.0)
        home_ga = home_defense.get('goals_against_per_game', 3.0)
        away_gf = away_defense.get('goals_for_per_game', 3.0)
        away_ga = away_defense.get('goals_against_per_game', 3.0)

        # Expected goals for each team
        # Home team expected = (home_gf + away_ga) / 2 * home_ice_advantage
        home_expected = ((home_gf + away_ga) / 2) * 1.05  # 5% home ice advantage
        away_expected = (away_gf + home_ga) / 2

        expected_total = home_expected + away_expected
        expected_margin = home_expected - away_expected

        context['home_expected_goals'] = home_expected
        context['away_expected_goals'] = away_expected
        context['expected_total'] = expected_total
        context['expected_margin'] = expected_margin

        implied_prob = self._american_to_prob(odds)

        if market_key == 'h2h':
            # Moneyline - estimate win probability
            # Simple: if expected margin > 0, home favored
            import math

            # Convert expected margin to win probability using logistic function
            if outcome_name == home_team or home_abbrev in outcome_name:
                # Home team selected
                model_prob = 1 / (1 + math.exp(-expected_margin * 0.5))
            else:
                # Away team selected
                model_prob = 1 / (1 + math.exp(expected_margin * 0.5))

            edge_pct = (model_prob - implied_prob) * 100
            context['model_prob'] = model_prob

        elif market_key == 'spreads':
            # Puck line - usually -1.5/+1.5
            # Check if our expected margin covers the spread
            import math

            # Positive line = underdog (getting points)
            # Negative line = favorite (giving points)
            adjusted_margin = expected_margin + line  # line is negative for favorite

            # Probability of covering based on adjusted margin
            # Rough model: each 0.5 goal margin = ~15% swing
            model_prob = 1 / (1 + math.exp(-adjusted_margin * 0.4))

            edge_pct = (model_prob - implied_prob) * 100
            context['model_prob'] = model_prob
            context['adjusted_margin'] = adjusted_margin

        elif market_key == 'totals':
            # Game total over/under
            import math

            diff_from_line = expected_total - line

            # Probability of over based on expected vs line
            # Each 0.5 goal diff = ~20% swing
            if 'over' in outcome_name.lower():
                model_prob = 1 / (1 + math.exp(-diff_from_line * 0.4))
            else:  # under
                model_prob = 1 / (1 + math.exp(diff_from_line * 0.4))

            edge_pct = (model_prob - implied_prob) * 100
            context['model_prob'] = model_prob
            context['diff_from_line'] = diff_from_line

        else:
            return None, context

        return edge_pct, context

    def process_date(self, game_date: str, max_events: int = None) -> int:
        """
        Process all markets for a single date.

        Returns number of props processed.
        """
        print(f"\n  Processing {game_date}...")

        # Fetch events
        events = self.odds_client.get_historical_events(game_date, use_cache=True)
        if not events:
            print(f"    No events found")
            return 0

        if max_events:
            events = events[:max_events]

        print(f"    Found {len(events)} events")
        props_processed = 0

        for event in events:
            event_id = event.get('id')
            home = event.get('home_team', '')
            away = event.get('away_team', '')
            matchup = f"{away}@{home}"

            # Fetch player prop markets
            try:
                odds_data = self.odds_client.get_historical_event_odds(
                    event_id=event_id,
                    date_str=game_date,
                    markets=ALL_PLAYER_MARKETS,
                    use_cache=True,
                )
            except Exception as e:
                print(f"      {matchup}: error fetching - {e}")
                continue

            data = odds_data.get('data', odds_data)
            bookmakers = data.get('bookmakers', [])

            # Process each bookmaker's props
            for bm in bookmakers:
                bm_key = bm.get('key')

                # Focus on DraftKings for consistency
                if bm_key != 'draftkings':
                    continue

                for market in bm.get('markets', []):
                    market_key = market.get('key')

                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description', '')
                        direction = outcome.get('name', '').lower()
                        odds = outcome.get('price', 0)
                        line = outcome.get('point', 0.5)

                        if not player_name:
                            continue

                        # Skip 'under' for O/U (we'll calculate from 'over')
                        if direction == 'under':
                            continue

                        stat_type = MARKET_TO_STAT_TYPE.get(market_key, market_key.replace('player_', ''))

                        # Calculate edge based on market type
                        # Need to try both teams to find the player
                        if market_key in PLAYER_OU_MARKETS:
                            # Try home team first, then away
                            edge, ctx = self.calculate_player_prop_edge(
                                player_name=player_name,
                                stat_type=stat_type,
                                line=line,
                                over_odds=odds,
                                game_date=game_date,
                                team=home,  # Try home team
                                opponent=away,
                            )
                            if not ctx.get('has_nhl_data'):
                                # Try away team
                                edge, ctx = self.calculate_player_prop_edge(
                                    player_name=player_name,
                                    stat_type=stat_type,
                                    line=line,
                                    over_odds=odds,
                                    game_date=game_date,
                                    team=away,
                                    opponent=home,
                                )
                        elif market_key in GOAL_SCORER_MARKETS:
                            # Try home team first, then away
                            edge, ctx = self.calculate_goal_scorer_edge(
                                player_name=player_name,
                                market_key=market_key,
                                odds=odds,
                                game_date=game_date,
                                team=home,
                                opponent=away,
                            )
                            if not ctx.get('has_nhl_data'):
                                edge, ctx = self.calculate_goal_scorer_edge(
                                    player_name=player_name,
                                    market_key=market_key,
                                    odds=odds,
                                    game_date=game_date,
                                    team=away,
                                    opponent=home,
                                )
                        else:
                            continue

                        # Record result
                        result = BacktestResult(
                            game_date=game_date,
                            event_id=event_id,
                            matchup=matchup,
                            player_name=player_name,
                            market_key=market_key,
                            stat_type=stat_type,
                            line=line,
                            direction=direction,
                            odds=odds,
                            implied_prob=american_to_implied_prob(odds),
                            model_prob=ctx.get('model_prob'),
                            edge_pct=edge,
                            has_nhl_data=ctx.get('has_nhl_data', False),
                            has_pipeline_data=ctx.get('has_pipeline_data', False),
                            actual_result=None,
                            context=ctx,
                        )

                        self.results.append(result)
                        props_processed += 1

                        # Update market stats
                        stats = self.market_stats[market_key]
                        stats['total'] += 1
                        if ctx.get('has_nhl_data'):
                            stats['with_nhl_data'] += 1
                        if ctx.get('has_pipeline_data'):
                            stats['with_pipeline_data'] += 1
                        if edge is not None:
                            stats['with_edge'] += 1
                            if len(stats['samples']) < 5:
                                stats['samples'].append({
                                    'player': player_name,
                                    'edge': edge,
                                    'odds': odds,
                                })

            # Also fetch game lines (h2h, spreads, totals)
            try:
                game_odds_data = self.odds_client.get_historical_event_odds(
                    event_id=event_id,
                    date_str=game_date,
                    markets=CORE_GAME_MARKETS,
                    use_cache=True,
                )
            except Exception as e:
                print(f"      {matchup}: error fetching game lines - {e}")
                game_odds_data = {}

            game_data = game_odds_data.get('data', game_odds_data)
            game_bookmakers = game_data.get('bookmakers', [])

            for bm in game_bookmakers:
                bm_key = bm.get('key')
                if bm_key != 'draftkings':
                    continue

                for market in bm.get('markets', []):
                    market_key = market.get('key')

                    if market_key not in CORE_GAME_MARKETS:
                        continue

                    for outcome in market.get('outcomes', []):
                        outcome_name = outcome.get('name', '')
                        odds = outcome.get('price', 0)
                        line = outcome.get('point', 0)

                        # For h2h, skip draw if present
                        if market_key == 'h2h' and 'draw' in outcome_name.lower():
                            continue

                        # For totals, only process 'Over' (skip 'Under')
                        if market_key == 'totals' and 'under' in outcome_name.lower():
                            continue

                        # For spreads, process both sides (they have different lines)
                        edge, ctx = self.calculate_game_line_edge(
                            market_key=market_key,
                            outcome_name=outcome_name,
                            odds=odds,
                            line=line,
                            home_team=home,
                            away_team=away,
                            game_date=game_date,
                        )

                        # Record result
                        result = BacktestResult(
                            game_date=game_date,
                            event_id=event_id,
                            matchup=matchup,
                            player_name=outcome_name,  # Team name or Over/Under
                            market_key=market_key,
                            stat_type=market_key,
                            line=line,
                            direction=outcome_name.lower(),
                            odds=odds,
                            implied_prob=american_to_implied_prob(odds),
                            model_prob=ctx.get('model_prob'),
                            edge_pct=edge,
                            has_nhl_data=ctx.get('has_nhl_data', False),
                            has_pipeline_data=False,
                            actual_result=None,
                            context=ctx,
                        )

                        self.results.append(result)
                        props_processed += 1

                        # Update market stats
                        stats = self.market_stats[market_key]
                        stats['total'] += 1
                        if ctx.get('has_nhl_data'):
                            stats['with_nhl_data'] += 1
                        if edge is not None:
                            stats['with_edge'] += 1
                            if len(stats['samples']) < 5:
                                stats['samples'].append({
                                    'player': outcome_name,
                                    'edge': edge,
                                    'odds': odds,
                                })

        print(f"    Processed {props_processed} props")
        return props_processed

    def run(
        self,
        dates: List[str] = None,
        max_dates: int = None,
        max_events_per_date: int = None,
    ) -> Dict:
        """
        Run the comprehensive backtest.

        Returns summary statistics.
        """
        dates = dates or get_november_game_dates()
        if max_dates:
            dates = dates[:max_dates]

        print(f"=" * 70)
        print(f"COMPREHENSIVE NOVEMBER BACKTEST")
        print(f"=" * 70)
        print(f"Dates to process: {len(dates)}")
        print(f"Markets: {len(ALL_PLAYER_MARKETS)}")

        # Check API budget
        status = self.odds_client.test_connection()
        print(f"\nAPI calls remaining: {status.get('requests_remaining')}")

        total_props = 0
        for game_date in dates:
            count = self.process_date(game_date, max_events=max_events_per_date)
            total_props += count

        return self.generate_summary()

    def generate_summary(self) -> Dict:
        """Generate summary statistics by market."""
        print(f"\n{'='*70}")
        print("BACKTEST RESULTS BY MARKET")
        print(f"{'='*70}\n")

        summary = {
            'total_props': len(self.results),
            'by_market': {},
        }

        # Calculate stats by market
        for market_key, stats in sorted(self.market_stats.items()):
            total = stats['total']
            with_data = stats['with_nhl_data']
            with_edge = stats['with_edge']

            # Calculate average edge for props with positive edge
            positive_edges = [
                r.edge_pct for r in self.results
                if r.market_key == market_key and r.edge_pct is not None and r.edge_pct > 0
            ]
            avg_positive_edge = sum(positive_edges) / len(positive_edges) if positive_edges else 0

            # Edge distribution
            edge_buckets = {'0-5%': 0, '5-10%': 0, '10-15%': 0, '15%+': 0}
            for r in self.results:
                if r.market_key == market_key and r.edge_pct is not None and r.edge_pct > 0:
                    if r.edge_pct < 5:
                        edge_buckets['0-5%'] += 1
                    elif r.edge_pct < 10:
                        edge_buckets['5-10%'] += 1
                    elif r.edge_pct < 15:
                        edge_buckets['10-15%'] += 1
                    else:
                        edge_buckets['15%+'] += 1

            summary['by_market'][market_key] = {
                'total': total,
                'with_nhl_data': with_data,
                'with_nhl_data_pct': (with_data / total * 100) if total > 0 else 0,
                'with_edge': with_edge,
                'positive_edge_count': len(positive_edges),
                'avg_positive_edge': avg_positive_edge,
                'edge_distribution': edge_buckets,
                'samples': stats['samples'],
            }

            # Print summary
            data_pct = (with_data / total * 100) if total > 0 else 0
            pos_edge_pct = (len(positive_edges) / total * 100) if total > 0 else 0

            print(f"{market_key:30}")
            print(f"  Total props: {total:>6}")
            print(f"  With NHL data: {with_data:>4} ({data_pct:.1f}%)")
            print(f"  Positive edge: {len(positive_edges):>4} ({pos_edge_pct:.1f}%)")
            print(f"  Avg positive edge: {avg_positive_edge:.1f}%")
            print(f"  Edge buckets: {edge_buckets}")
            print()

        # Overall summary
        total_with_data = sum(s['with_nhl_data'] for s in summary['by_market'].values())
        total_positive_edge = sum(s['positive_edge_count'] for s in summary['by_market'].values())

        print(f"{'='*70}")
        print("OVERALL SUMMARY")
        print(f"{'='*70}")
        print(f"Total props analyzed: {summary['total_props']}")
        print(f"Props with NHL data: {total_with_data} ({total_with_data/summary['total_props']*100:.1f}%)")
        print(f"Props with positive edge: {total_positive_edge}")

        # Identify most promising markets
        print(f"\n{'='*70}")
        print("MARKET RANKINGS (by positive edge %)")
        print(f"{'='*70}")

        rankings = []
        for market, stats in summary['by_market'].items():
            if stats['total'] > 10:  # Minimum sample size
                pos_rate = stats['positive_edge_count'] / stats['total'] * 100
                rankings.append((market, pos_rate, stats['avg_positive_edge'], stats['total']))

        rankings.sort(key=lambda x: x[1], reverse=True)

        print(f"\n{'Market':<30} | {'Pos Edge %':>10} | {'Avg Edge':>8} | {'Volume':>6}")
        print("-" * 65)
        for market, pos_rate, avg_edge, volume in rankings:
            print(f"{market:<30} | {pos_rate:>9.1f}% | {avg_edge:>7.1f}% | {volume:>6}")

        summary['rankings'] = [
            {'market': m, 'positive_edge_pct': p, 'avg_edge': a, 'volume': v}
            for m, p, a, v in rankings
        ]

        return summary


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dates', type=int, default=10, help='Number of dates to backtest')
    parser.add_argument('--events', type=int, default=None, help='Max events per date')
    args = parser.parse_args()

    backtest = ComprehensiveBacktest()

    # Run backtest
    print("\n" + "=" * 70)
    print(f"COMPREHENSIVE BACKTEST ({args.dates} dates)")
    print("=" * 70)

    summary = backtest.run(
        max_dates=args.dates,
        max_events_per_date=args.events,
    )

    # Save results
    output_dir = Path(__file__).parent.parent / 'data'
    output_dir.mkdir(exist_ok=True)

    # Save summary
    summary_path = output_dir / 'november_backtest_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSummary saved to: {summary_path}")

    # Save detailed results
    results_path = output_dir / 'november_backtest_detailed.json'
    with open(results_path, 'w') as f:
        json.dump([asdict(r) for r in backtest.results], f, indent=2, default=str)
    print(f"Detailed results saved to: {results_path}")

    # API usage
    usage = backtest.odds_client.get_usage_summary()
    print(f"\nAPI Usage: {usage['requests_used']} used, {usage['requests_remaining']} remaining")

    return summary


if __name__ == '__main__':
    main()
