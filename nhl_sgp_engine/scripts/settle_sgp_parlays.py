"""
NHL SGP Parlay Settlement

Production settlement workflow aligned with NFL/NCAAF architecture:
1. Fetch unsettled parlays from database
2. Get box scores from NHL API
3. Settle each leg (WIN/LOSS/PUSH/VOID)
4. Calculate parlay result (WIN if all legs hit)
5. Create settlement record with profit calculation

Usage:
    python -m nhl_sgp_engine.scripts.settle_sgp_parlays
    python -m nhl_sgp_engine.scripts.settle_sgp_parlays --date 2025-12-14
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from providers.nhl_official_api import NHLOfficialAPI
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.providers.nhl_data_provider import normalize_team


class SGPParlaySettlement:
    """Settle NHL SGP parlays against actual game results."""

    def __init__(self):
        self.nhl_api = NHLOfficialAPI()
        self.db = NHLSGPDBManager()
        self.box_score_cache: Dict[int, Dict] = {}

    def get_game_id_for_matchup(self, game_date: date, home_team: str, away_team: str) -> Optional[int]:
        """Find NHL game ID for a matchup."""
        games = self.nhl_api.get_games_by_date(game_date)

        for game in games:
            if game['away_team'] == away_team and game['home_team'] == home_team:
                return game['game_id']

        return None

    def get_box_score(self, game_id: int) -> Optional[Dict]:
        """Get box score with caching."""
        if game_id in self.box_score_cache:
            return self.box_score_cache[game_id]

        box_score = self.nhl_api.get_box_score(game_id)
        if box_score:
            self.box_score_cache[game_id] = box_score
        return box_score

    def find_player_stats(self, box_score: Dict, player_name: str) -> Optional[Dict]:
        """Find player stats in box score by name."""
        if not box_score or 'players' not in box_score:
            return None

        search_name = player_name.lower().strip()

        for player in box_score['players']:
            player_box_name = (player.get('name') or '').lower().strip()

            if player_box_name == search_name:
                return player

            # Last name match
            search_parts = search_name.split()
            box_parts = player_box_name.split()

            if len(search_parts) >= 2 and len(box_parts) >= 2:
                if search_parts[-1] == box_parts[-1]:
                    return player

        return None

    def get_actual_value(self, player_stats: Dict, stat_type: str) -> Optional[float]:
        """Extract actual stat value from player stats."""
        stat_mapping = {
            'points': 'points',
            'goals': 'goals',
            'assists': 'assists',
            'shots_on_goal': 'shots',
            'blocked_shots': 'blocked_shots',
            'power_play_points': 'power_play_goals',  # Approximation
            'total_saves': 'saves',
        }

        mapped_stat = stat_mapping.get(stat_type)
        if not mapped_stat:
            return None

        value = player_stats.get(mapped_stat)
        if value is None:
            return None

        return float(value)

    def settle_leg(self, leg: Dict, box_score: Dict) -> Dict:
        """
        Settle a single leg against box score.

        Returns dict with actual_value and result.
        """
        player_name = leg['player_name']
        stat_type = leg['stat_type']
        line = float(leg['line'])
        direction = leg['direction']

        # Find player in box score
        player_stats = self.find_player_stats(box_score, player_name)
        if not player_stats:
            return {
                'actual_value': None,
                'result': 'VOID',
                'reason': f"Player {player_name} not found in box score",
            }

        # Get actual value
        actual_value = self.get_actual_value(player_stats, stat_type)
        if actual_value is None:
            return {
                'actual_value': None,
                'result': 'VOID',
                'reason': f"Stat {stat_type} not found for {player_name}",
            }

        # Determine result
        if direction == 'over':
            if actual_value > line:
                result = 'WIN'
            elif actual_value == line:
                result = 'PUSH'
            else:
                result = 'LOSS'
        else:  # under
            if actual_value < line:
                result = 'WIN'
            elif actual_value == line:
                result = 'PUSH'
            else:
                result = 'LOSS'

        return {
            'actual_value': actual_value,
            'result': result,
            'reason': f"{player_name}: {actual_value} vs {direction} {line}",
        }

    def calculate_profit(self, combined_odds: int, result: str) -> float:
        """Calculate profit at $100 stake."""
        if result != 'WIN':
            if result == 'LOSS':
                return -100.0
            return 0.0  # VOID or PUSH

        if combined_odds > 0:
            return float(combined_odds)
        else:
            return float(100 * 100 / abs(combined_odds))

    def settle_parlay(self, parlay: Dict, legs: List[Dict]) -> Optional[Dict]:
        """
        Settle a parlay and all its legs.

        Returns settlement record or None if can't settle.
        """
        game_date = parlay['game_date']
        home_team = parlay['home_team']
        away_team = parlay['away_team']

        # Get game ID
        game_id = self.get_game_id_for_matchup(game_date, home_team, away_team)
        if not game_id:
            print(f"  Could not find game: {away_team}@{home_team}")
            return None

        # Get box score
        box_score = self.get_box_score(game_id)
        if not box_score:
            print(f"  Could not get box score for game {game_id}")
            return None

        # Check game is final
        game_state = box_score.get('game_state', '')
        if game_state not in ['OFF', 'FINAL']:
            print(f"  Game not final (state: {game_state})")
            return None

        # Settle each leg
        leg_results = []
        for leg in legs:
            result = self.settle_leg(leg, box_score)
            leg_results.append({
                'leg_id': leg['id'],
                'actual_value': result['actual_value'],
                'result': result['result'],
            })

        # Calculate parlay result
        non_void_results = [r for r in leg_results if r['result'] != 'VOID']
        if not non_void_results:
            parlay_result = 'VOID'
        elif all(r['result'] == 'WIN' for r in non_void_results):
            parlay_result = 'WIN'
        elif all(r['result'] in ['WIN', 'PUSH'] for r in non_void_results):
            # All wins and pushes - push on pushes, win on rest
            if any(r['result'] == 'PUSH' for r in non_void_results):
                # Recalculate odds without pushed legs
                parlay_result = 'WIN'  # Simplified - full parlay with pushes
            else:
                parlay_result = 'WIN'
        else:
            parlay_result = 'LOSS'

        # Calculate profit
        profit = self.calculate_profit(parlay['combined_odds'], parlay_result)

        # Create settlement record
        settlement = {
            'id': uuid.uuid4(),
            'parlay_id': parlay['id'],
            'legs_hit': sum(1 for r in leg_results if r['result'] == 'WIN'),
            'total_legs': len([r for r in leg_results if r['result'] != 'VOID']),
            'result': parlay_result,
            'profit': Decimal(str(profit)),
            'settled_at': datetime.utcnow(),
            'notes': f"Settled {datetime.utcnow().isoformat()}",
        }

        return {
            'settlement': settlement,
            'leg_results': leg_results,
        }

    def run(self, game_date: date = None) -> Dict:
        """
        Run settlement for a specific date.

        Args:
            game_date: Date to settle (default: yesterday)

        Returns:
            Summary dict
        """
        game_date = game_date or (date.today() - timedelta(days=1))

        print("=" * 70)
        print(f"NHL SGP SETTLEMENT - {game_date}")
        print("=" * 70)

        # Get unsettled parlays for this date
        parlays = self.db.get_parlays_by_date(game_date)

        # Filter to unsettled (no settlement record yet)
        unsettled_parlays = []
        for p in parlays:
            # Check if already settled by querying settlements
            # For now, check if legs have results
            legs = p.get('legs', [])
            if legs and all(leg.get('result') is None for leg in legs):
                unsettled_parlays.append(p)

        if not unsettled_parlays:
            print(f"[Settlement] No unsettled parlays for {game_date}")
            return {'settled': 0, 'game_date': str(game_date)}

        print(f"[Settlement] Found {len(unsettled_parlays)} unsettled parlays")

        # Settle each parlay
        settled_count = 0
        total_profit = 0.0
        wins = 0

        for parlay in unsettled_parlays:
            matchup = f"{parlay['away_team']}@{parlay['home_team']}"
            print(f"\n  Settling: {matchup}")

            # Parse legs from JSON
            legs = parlay.get('legs', [])
            if not legs:
                print(f"    No legs found")
                continue

            result = self.settle_parlay(parlay, legs)
            if not result:
                continue

            settlement = result['settlement']
            leg_results = result['leg_results']

            # Update database
            try:
                # Update legs
                with self.db.Session() as session:
                    for lr in leg_results:
                        session.execute(
                            self.db.nhl_sgp_legs_table.update().where(
                                self.db.nhl_sgp_legs_table.c.id == lr['leg_id']
                            ).values(
                                actual_value=lr['actual_value'],
                                result=lr['result'],
                            )
                        )
                    session.commit()

                # Insert settlement
                with self.db.Session() as session:
                    session.execute(
                        self.db.nhl_sgp_settlements_table.insert().values(**settlement)
                    )
                    session.commit()

                settled_count += 1
                total_profit += float(settlement['profit'])
                if settlement['result'] == 'WIN':
                    wins += 1

                print(f"    Result: {settlement['result']} | Legs: {settlement['legs_hit']}/{settlement['total_legs']} | Profit: ${settlement['profit']}")

            except Exception as e:
                print(f"    Error saving settlement: {e}")

        # Summary
        print(f"\n{'='*70}")
        print("SETTLEMENT RESULTS")
        print(f"{'='*70}")
        print(f"Parlays settled: {settled_count}")
        print(f"Wins: {wins}")
        print(f"Win rate: {wins/settled_count*100:.1f}%" if settled_count > 0 else "N/A")
        print(f"Total profit: ${total_profit:.2f}")

        return {
            'game_date': str(game_date),
            'settled': settled_count,
            'wins': wins,
            'win_rate': wins / settled_count * 100 if settled_count > 0 else 0,
            'profit': total_profit,
        }


def main():
    parser = argparse.ArgumentParser(description='Settle NHL SGP parlays')
    parser.add_argument('--date', type=str, help='Date to settle (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--all', action='store_true', help='Settle all unsettled parlays')
    args = parser.parse_args()

    settler = SGPParlaySettlement()

    if args.all:
        # Get all dates with unsettled parlays
        print("[Settlement] Finding all unsettled parlays...")
        # Would need a method to get all unsettled dates
        # For now, settle last 7 days
        for i in range(7):
            d = date.today() - timedelta(days=i+1)
            result = settler.run(game_date=d)
            if result['settled'] > 0:
                print(f"  {d}: {result['settled']} settled, {result.get('win_rate', 0):.1f}% win rate")
    else:
        game_date = date.fromisoformat(args.date) if args.date else (date.today() - timedelta(days=1))
        result = settler.run(game_date=game_date)

    print("\n[Settlement] Complete")


if __name__ == '__main__':
    main()
