"""
NHL SGP Daily Parlay Generator

Production workflow aligned with NFL/NCAAF SGP architecture:
1. Fetch today's games from Odds API
2. Fetch current odds for player props (validated markets only)
3. Calculate edge using NHL API data
4. Group props by game, select best 3-4 legs per game
5. Generate parlay with thesis narrative
6. Write to nhl_sgp_parlays + nhl_sgp_legs tables

Usage:
    python -m nhl_sgp_engine.scripts.daily_sgp_generator
    python -m nhl_sgp_engine.scripts.daily_sgp_generator --date 2025-12-15
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from collections import defaultdict
from zoneinfo import ZoneInfo

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.providers.context_builder import PropContextBuilder
from nhl_sgp_engine.providers.nhl_data_provider import NHLDataProvider, normalize_team
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.config.markets import MARKET_TO_STAT_TYPE


# =============================================================================
# Production Filters (validated by November backtest)
# =============================================================================

# Markets validated with positive edge correlation
VALIDATED_MARKETS = [
    'player_points',        # 46.0% hit rate at 10-15% edge
    'player_shots_on_goal', # 50.1% hit rate
]

# Edge thresholds (10-15% bucket showed 49.6% hit rate)
MIN_EDGE_PCT = 10.0
MAX_EDGE_PCT = 25.0

# Parlay configuration
MIN_LEGS_PER_PARLAY = 3
MAX_LEGS_PER_PARLAY = 4
MAX_LEGS_PER_PLAYER = 1  # Avoid overloading one player


class NHLSGPGenerator:
    """Generate multi-leg SGP parlays for NHL games."""

    def __init__(self):
        self.odds_client = OddsAPIClient()
        self.context_builder = PropContextBuilder()
        self.nhl_provider = NHLDataProvider()
        self.edge_calculator = EdgeCalculator()
        self.db = NHLSGPDBManager()

    def _american_to_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)

    def _american_to_decimal(self, odds: int) -> float:
        """Convert American odds to decimal odds."""
        if odds > 0:
            return (odds / 100) + 1
        else:
            return (100 / abs(odds)) + 1

    def _decimal_to_american(self, decimal_odds: float) -> int:
        """Convert decimal odds to American odds."""
        if decimal_odds >= 2.0:
            return int((decimal_odds - 1) * 100)
        else:
            return int(-100 / (decimal_odds - 1))

    def _calculate_combined_odds(self, legs: List[Dict]) -> Tuple[int, float]:
        """
        Calculate combined parlay odds.

        Returns:
            (american_odds, implied_probability)
        """
        combined_decimal = 1.0
        for leg in legs:
            leg_decimal = self._american_to_decimal(leg['odds'])
            combined_decimal *= leg_decimal

        american = self._decimal_to_american(combined_decimal)
        implied_prob = 1 / combined_decimal

        return american, implied_prob

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
                # Player info from context
                'team': ctx.team,
                'position': ctx.position,
                'player_id': ctx.player_id,
            }
        except Exception as e:
            return None

    def fetch_todays_props(self, game_date: date) -> Dict[str, List[Dict]]:
        """
        Fetch props for today's games from Odds API.

        Returns:
            Dict mapping game_id -> list of props
        """
        print(f"\n[SGP Generator] Fetching props for {game_date}...")

        try:
            events = self.odds_client.get_current_events()
        except Exception as e:
            print(f"[SGP Generator] Error fetching events: {e}")
            return {}

        # Filter to today's games
        # NOTE: Odds API returns commence_time in UTC. Evening games (7 PM ET)
        # are midnight UTC next day. Convert to ET for proper date matching.
        et_tz = ZoneInfo('America/New_York')
        todays_events = []
        for event in events:
            commence_time = event.get('commence_time', '')
            if commence_time:
                # Parse UTC time and convert to Eastern
                utc_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                et_dt = utc_dt.astimezone(et_tz)
                if et_dt.date() == game_date:
                    todays_events.append(event)

        print(f"[SGP Generator] Found {len(todays_events)} games today")

        if not todays_events:
            return {}

        props_by_game = {}

        for event in todays_events:
            event_id = event.get('id')
            home = normalize_team(event.get('home_team', ''))
            away = normalize_team(event.get('away_team', ''))
            game_id = f"2025_NHL_{away}_{home}_{game_date.strftime('%Y%m%d')}"
            matchup = f"{away}@{home}"

            # Fetch player props for this event
            try:
                event_odds = self.odds_client.get_event_odds(
                    event_id=event_id,
                    markets=VALIDATED_MARKETS,
                )
            except Exception as e:
                print(f"[SGP Generator] Error fetching odds for {matchup}: {e}")
                continue

            game_props = []

            # Prefer DraftKings, fall back to first available bookmaker
            bookmakers = event_odds.get('bookmakers', [])
            if not bookmakers:
                # No props available for this game yet - skip silently
                continue

            dk_books = [b for b in bookmakers if b.get('key') == 'draftkings']
            selected_bookmaker = dk_books[0] if dk_books else bookmakers[0]

            for bm in [selected_bookmaker]:

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

                        game_props.append({
                            'event_id': event_id,
                            'game_id': game_id,
                            'matchup': matchup,
                            'home_team': home,
                            'away_team': away,
                            'player_name': player_name,
                            'market_key': market_key,
                            'stat_type': MARKET_TO_STAT_TYPE.get(market_key, market_key.replace('player_', '')),
                            'line': line,
                            'odds': odds,
                        })

            if game_props:
                props_by_game[game_id] = {
                    'game_id': game_id,
                    'home_team': home,
                    'away_team': away,
                    'matchup': matchup,
                    'props': game_props,
                }

        total_props = sum(len(g['props']) for g in props_by_game.values())
        print(f"[SGP Generator] Found {total_props} props across {len(props_by_game)} games")
        return props_by_game

    def calculate_all_edges(self, props_by_game: Dict, game_date: date) -> Dict:
        """Calculate edges for all props and return only actionable ones."""
        print(f"\n[SGP Generator] Calculating edges...")

        actionable_by_game = {}
        total_processed = 0
        total_actionable = 0

        for game_id, game_data in props_by_game.items():
            actionable_props = []

            for prop in game_data['props']:
                total_processed += 1

                # Try home team first, then away team
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

                # Merge prop data with edge data
                actionable_prop = {**prop, **edge_data}
                actionable_props.append(actionable_prop)
                total_actionable += 1

            if actionable_props:
                actionable_by_game[game_id] = {
                    **game_data,
                    'actionable_props': actionable_props,
                }

        print(f"[SGP Generator] Processed {total_processed}, found {total_actionable} actionable props")
        return actionable_by_game

    def generate_thesis(self, game_data: Dict, legs: List[Dict]) -> str:
        """Generate a narrative thesis for the parlay."""
        home = game_data['home_team']
        away = game_data['away_team']

        # Analyze leg composition
        stat_types = [leg['stat_type'] for leg in legs]
        teams = [leg.get('team', 'UNK') for leg in legs]
        avg_edge = sum(leg['edge_pct'] for leg in legs) / len(legs)

        # Build thesis based on composition
        thesis_parts = []

        # Check for offensive theme
        if stat_types.count('points') >= 2:
            thesis_parts.append(f"Offensive-focused parlay targeting point production")

        # Check for shooting theme
        if stat_types.count('shots_on_goal') >= 2:
            thesis_parts.append(f"High-volume shooting game expected")

        # Check for team stack
        team_counts = defaultdict(int)
        for t in teams:
            team_counts[t] += 1
        stacked_team = max(team_counts.keys(), key=lambda x: team_counts[x])
        if team_counts[stacked_team] >= 2:
            thesis_parts.append(f"Stacking {stacked_team} players")

        # Add edge summary
        thesis_parts.append(f"Average edge: {avg_edge:.1f}%")

        # Add primary reasons from top legs
        top_reasons = [leg['primary_reason'] for leg in sorted(legs, key=lambda x: x['edge_pct'], reverse=True)[:2]]
        for reason in top_reasons:
            if reason:
                thesis_parts.append(reason)

        return " | ".join(thesis_parts)

    def select_parlay_legs(self, actionable_props: List[Dict]) -> List[Dict]:
        """
        Select optimal legs for a parlay from actionable props.

        Rules:
        - 3-4 legs per parlay
        - Max 1 leg per player
        - Prioritize by edge percentage
        - Diversify stat types if possible
        """
        # Sort by edge
        sorted_props = sorted(actionable_props, key=lambda x: x['edge_pct'], reverse=True)

        selected = []
        used_players = set()

        for prop in sorted_props:
            if len(selected) >= MAX_LEGS_PER_PARLAY:
                break

            player = prop['player_name']
            if player in used_players:
                continue

            selected.append(prop)
            used_players.add(player)

        return selected if len(selected) >= MIN_LEGS_PER_PARLAY else []

    def create_parlay_record(
        self,
        game_data: Dict,
        legs: List[Dict],
        game_date: date,
        parlay_type: str = 'primary',
    ) -> Tuple[Dict, List[Dict]]:
        """
        Create parlay and legs records for database insertion.

        Returns:
            (parlay_record, leg_records)
        """
        combined_odds, implied_prob = self._calculate_combined_odds(legs)
        thesis = self.generate_thesis(game_data, legs)

        # Determine game slot based on time (simplified)
        game_slot = 'EVENING'  # Default; could parse from commence_time

        parlay_record = {
            'id': uuid.uuid4(),
            'parlay_type': parlay_type,
            'game_id': game_data['game_id'],
            'game_date': game_date,
            'home_team': game_data['home_team'],
            'away_team': game_data['away_team'],
            'game_slot': game_slot,
            'total_legs': len(legs),
            'combined_odds': combined_odds,
            'implied_probability': Decimal(str(round(implied_prob, 4))),
            'thesis': thesis,
            'season': game_date.year if game_date.month >= 9 else game_date.year - 1,
            'season_type': 'regular',
        }

        leg_records = []
        for i, leg in enumerate(legs, 1):
            leg_record = {
                'id': uuid.uuid4(),
                'parlay_id': parlay_record['id'],
                'leg_number': i,
                'player_name': leg['player_name'],
                'player_id': leg.get('player_id'),
                'team': leg.get('team'),
                'position': leg.get('position'),
                'stat_type': leg['stat_type'],
                'line': Decimal(str(leg['line'])),
                'direction': 'over',  # We only bet overs currently
                'odds': leg['odds'],
                'edge_pct': Decimal(str(round(leg['edge_pct'], 2))),
                'confidence': Decimal(str(round(leg['confidence'], 2))),
                'model_probability': Decimal(str(round(leg['model_probability'], 4))),
                'market_probability': Decimal(str(round(leg['market_probability'], 4))),
                'primary_reason': leg['primary_reason'],
                'supporting_reasons': [],
                'risk_factors': [],
                'signals': leg.get('signals', {}),
            }
            leg_records.append(leg_record)

        return parlay_record, leg_records

    def run(self, game_date: date = None, dry_run: bool = False) -> Dict:
        """
        Run the SGP generation pipeline.

        Args:
            game_date: Date to generate parlays for (default: today)
            dry_run: If True, don't write to database

        Returns:
            Summary dict
        """
        game_date = game_date or date.today()

        print("=" * 70)
        print(f"NHL SGP GENERATOR - {game_date}")
        print("=" * 70)

        # Check API budget
        status = self.odds_client.test_connection()
        print(f"\nOdds API remaining: {status.get('requests_remaining')}")

        # Fetch props grouped by game
        props_by_game = self.fetch_todays_props(game_date)
        if not props_by_game:
            print("[SGP Generator] No props found for today")
            return {'parlays': 0, 'game_date': str(game_date)}

        # Calculate edges
        actionable_by_game = self.calculate_all_edges(props_by_game, game_date)
        if not actionable_by_game:
            print("[SGP Generator] No actionable props found")
            return {'parlays': 0, 'game_date': str(game_date)}

        # Generate parlays for each game
        parlays_created = 0
        all_parlays = []

        for game_id, game_data in actionable_by_game.items():
            legs = self.select_parlay_legs(game_data['actionable_props'])

            if not legs:
                print(f"  {game_data['matchup']}: Not enough quality legs")
                continue

            parlay, leg_records = self.create_parlay_record(
                game_data=game_data,
                legs=legs,
                game_date=game_date,
                parlay_type='primary',
            )

            all_parlays.append({
                'parlay': parlay,
                'legs': leg_records,
                'matchup': game_data['matchup'],
            })
            parlays_created += 1

        # Display parlays
        print(f"\n{'='*70}")
        print("GENERATED PARLAYS")
        print(f"{'='*70}")

        for p in all_parlays:
            parlay = p['parlay']
            legs = p['legs']
            matchup = p['matchup']

            print(f"\n{matchup} | {parlay['parlay_type'].upper()} | +{parlay['combined_odds']}")
            print(f"Thesis: {parlay['thesis'][:80]}...")
            print("-" * 50)
            for leg in legs:
                print(f"  {leg['leg_number']}. {leg['player_name']} {leg['stat_type']} O{leg['line']} ({leg['odds']:+d}) | Edge: {leg['edge_pct']}%")

        # Save to database
        if not dry_run and all_parlays:
            print(f"\n[SGP Generator] Saving {len(all_parlays)} parlays to database...")
            self.db.create_tables()

            for p in all_parlays:
                try:
                    parlay_id = self.db.upsert_parlay(p['parlay'])
                    self.db.upsert_legs(parlay_id, p['legs'])
                except Exception as e:
                    print(f"[SGP Generator] Error saving parlay: {e}")

            print(f"[SGP Generator] Saved {len(all_parlays)} parlays")
        else:
            print(f"\n[SGP Generator] DRY RUN - would save {len(all_parlays)} parlays")

        # Summary
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"Games with parlays: {parlays_created}")
        print(f"Total legs: {sum(len(p['legs']) for p in all_parlays)}")

        if all_parlays:
            avg_odds = sum(p['parlay']['combined_odds'] for p in all_parlays) / len(all_parlays)
            avg_legs = sum(len(p['legs']) for p in all_parlays) / len(all_parlays)
            print(f"Avg odds: +{avg_odds:.0f}")
            print(f"Avg legs: {avg_legs:.1f}")

        return {
            'game_date': str(game_date),
            'parlays': parlays_created,
            'total_legs': sum(len(p['legs']) for p in all_parlays),
        }


def main():
    parser = argparse.ArgumentParser(description='Generate NHL SGP parlays')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD), default: today')
    parser.add_argument('--dry-run', action='store_true', help='Do not write to database')
    args = parser.parse_args()

    game_date = date.fromisoformat(args.date) if args.date else date.today()

    generator = NHLSGPGenerator()
    result = generator.run(game_date=game_date, dry_run=args.dry_run)

    print(f"\n[SGP Generator] Complete: {result['parlays']} parlays for {result['game_date']}")
    return result


if __name__ == '__main__':
    main()
