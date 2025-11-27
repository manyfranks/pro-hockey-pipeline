# nhl_isolated/analytics/matchup_analyzer.py
"""
Matchup Analyzer for NHL Player Points Algorithm

Handles Skater-vs-Goalie (SvG) historical analysis.

Approach:
Since play-by-play data uses different player IDs (36xxxxxx) that don't map
to standard player IDs (30xxxxxx), we use a simplified approach:

1. For each completed game, identify the goalie(s) who played for each team
2. If only one goalie played (95% of games), all goals against = that goalie
3. Track skater points against each goalie over time
4. Build SvG history from box score data

References NHL_ALGORITHM_ADR.md Section 2.4
"""
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict


# Minimum games to consider SvG data "confident"
MIN_SVG_GAMES = 5

# SvG component weights
SVG_WEIGHT = 0.60  # Weight given to SvG data when confident
TEAM_DEFENSE_WEIGHT = 0.40  # Fallback weight


class SvGAnalyzer:
    """
    Analyzes historical Skater-vs-Goalie performance.

    Builds SvG records from box score data where goalie attribution
    is possible (single-goalie games).
    """

    def __init__(self, provider=None):
        """
        Initialize SvG analyzer.

        Args:
            provider: CachedNHLProvider instance for fetching box scores
        """
        self.provider = provider

        # SvG history: {(skater_id, goalie_id): {'games': N, 'points': N, 'goals': N, 'assists': N}}
        self.svg_history: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(
            lambda: {'games': 0, 'points': 0, 'goals': 0, 'assists': 0}
        )

        # Track which games we've processed
        self._processed_games: set = set()

    def build_svg_from_date_range(self, start_date: date, end_date: date,
                                    show_progress: bool = True) -> int:
        """
        Build SvG history from box scores in a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            show_progress: Print progress updates

        Returns:
            Number of games processed
        """
        if self.provider is None:
            print("[SvG] No provider configured")
            return 0

        games_processed = 0
        current = start_date
        total_days = (end_date - start_date).days + 1
        days_processed = 0

        while current <= end_date:
            try:
                box_scores = self.provider.get_box_scores_final(current)

                for box in box_scores:
                    game_id = box.get('Game', {}).get('GameID')
                    if game_id in self._processed_games:
                        continue

                    if self._process_box_score(box):
                        games_processed += 1
                        self._processed_games.add(game_id)

            except Exception as e:
                print(f"[SvG] Error processing {current}: {e}")

            days_processed += 1
            if show_progress and days_processed % 30 == 0:
                print(f"[SvG] Progress: {days_processed}/{total_days} days, {games_processed} games")

            current += timedelta(days=1)

        print(f"[SvG] Processed {games_processed} games, {len(self.svg_history)} SvG matchups tracked")
        return games_processed

    def build_svg_from_seasons(self, seasons: List[str] = None) -> int:
        """
        Build SvG history from one or more full seasons.

        Args:
            seasons: List of season strings (e.g., ['2024', '2025']).
                    If None, uses current + previous season.

        Returns:
            Total games processed
        """
        if self.provider is None:
            print("[SvG] No provider configured")
            return 0

        # Default: current season + last season
        if seasons is None:
            # Get current season info
            current_season_info = self.provider.get_current_season()
            current_season = current_season_info.get('Season', 2026)
            seasons = [str(current_season - 1), str(current_season)]  # e.g., ['2025', '2026']

        total_games = 0

        for season in seasons:
            season_int = int(season)

            # NHL season runs Oct to Jun (with playoffs)
            # Season "2025" means 2024-25, which runs Oct 2024 - Jun 2025
            start_year = season_int - 1
            end_year = season_int

            # Regular season: early Oct to mid-Apr
            reg_start = date(start_year, 10, 1)
            reg_end = date(end_year, 4, 20)

            # Playoffs: mid-Apr to late Jun
            playoff_start = date(end_year, 4, 15)
            playoff_end = date(end_year, 6, 30)

            print(f"\n[SvG] Loading season {season} ({start_year}-{end_year})...")

            # Regular season
            print(f"[SvG] Regular season: {reg_start} to {reg_end}")
            reg_games = self.build_svg_from_date_range(reg_start, reg_end, show_progress=True)
            total_games += reg_games

            # Playoffs (only if in the past)
            if playoff_end < date.today():
                print(f"[SvG] Playoffs: {playoff_start} to {playoff_end}")
                playoff_games = self.build_svg_from_date_range(playoff_start, playoff_end, show_progress=True)
                total_games += playoff_games

        return total_games

    def _process_box_score(self, box_score: Dict[str, Any]) -> bool:
        """
        Process a single box score to extract SvG data.

        Only processes games where we can confidently attribute goals
        to a specific goalie (single-goalie games).

        Args:
            box_score: Box score dictionary

        Returns:
            True if processed successfully
        """
        game_info = box_score.get('Game', {})
        player_games = box_score.get('PlayerGames', [])

        if not player_games:
            return False

        home_team = game_info.get('HomeTeam')
        away_team = game_info.get('AwayTeam')

        # Group players by team
        home_players = [p for p in player_games if p.get('Team') == home_team]
        away_players = [p for p in player_games if p.get('Team') == away_team]

        # Find goalies for each team (only those who played)
        home_goalies = [p for p in home_players if p.get('Position') == 'G'
                       and (p.get('GoaltendingMinutes') or 0) > 0]
        away_goalies = [p for p in away_players if p.get('Position') == 'G'
                       and (p.get('GoaltendingMinutes') or 0) > 0]

        # Skip if multiple goalies played (can't attribute precisely)
        if len(home_goalies) != 1 or len(away_goalies) != 1:
            return False

        home_goalie_id = home_goalies[0].get('PlayerID')
        away_goalie_id = away_goalies[0].get('PlayerID')

        # Process away skaters (faced home goalie)
        for player in away_players:
            if player.get('Position') == 'G':
                continue

            skater_id = player.get('PlayerID')
            goals = round(player.get('Goals', 0) or 0)
            assists = round(player.get('Assists', 0) or 0)
            points = goals + assists

            # Record SvG against home goalie
            key = (skater_id, home_goalie_id)
            self.svg_history[key]['games'] += 1
            self.svg_history[key]['points'] += points
            self.svg_history[key]['goals'] += goals
            self.svg_history[key]['assists'] += assists

        # Process home skaters (faced away goalie)
        for player in home_players:
            if player.get('Position') == 'G':
                continue

            skater_id = player.get('PlayerID')
            goals = round(player.get('Goals', 0) or 0)
            assists = round(player.get('Assists', 0) or 0)
            points = goals + assists

            # Record SvG against away goalie
            key = (skater_id, away_goalie_id)
            self.svg_history[key]['games'] += 1
            self.svg_history[key]['points'] += points
            self.svg_history[key]['goals'] += goals
            self.svg_history[key]['assists'] += assists

        return True

    def get_svg_stats(self, skater_id: int, goalie_id: int) -> Optional[Dict[str, Any]]:
        """
        Get SvG statistics for a specific skater-goalie matchup.

        Args:
            skater_id: Skater's player ID
            goalie_id: Goalie's player ID

        Returns:
            Dictionary with SvG stats, or None if no data
        """
        key = (skater_id, goalie_id)

        if key not in self.svg_history:
            return None

        data = self.svg_history[key]
        games = data['games']

        if games == 0:
            return None

        return {
            'games_faced': games,
            'total_points': data['points'],
            'total_goals': data['goals'],
            'total_assists': data['assists'],
            'ppg_vs_goalie': round(data['points'] / games, 3),
            'is_confident': games >= MIN_SVG_GAMES,
        }

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics about the SvG database."""
        if not self.svg_history:
            return {'total_matchups': 0}

        total_matchups = len(self.svg_history)
        confident_matchups = sum(1 for v in self.svg_history.values() if v['games'] >= MIN_SVG_GAMES)

        games_list = [v['games'] for v in self.svg_history.values()]
        avg_games = sum(games_list) / len(games_list) if games_list else 0

        return {
            'total_matchups': total_matchups,
            'confident_matchups': confident_matchups,
            'avg_games_per_matchup': round(avg_games, 2),
            'games_processed': len(self._processed_games),
        }


def calculate_matchup_score(
    player_data: Dict[str, Any],
    svg_analyzer: Optional[SvGAnalyzer] = None
) -> Dict[str, Any]:
    """
    Calculate the matchup score for a player.

    Uses SvG data if available and confident, otherwise falls back
    to goalie weakness as a proxy.

    Args:
        player_data: Enriched player dictionary
        svg_analyzer: SvGAnalyzer instance with loaded history

    Returns:
        Dictionary with:
        - matchup_score: Score (0-1 scale)
        - matchup_details: Breakdown of calculation
    """
    player_id = player_data.get('player_id')
    goalie_id = player_data.get('opposing_goalie_id')
    goalie_weakness = player_data.get('goalie_weakness_score', 0.5)

    # Try to get SvG data
    svg_stats = None
    if svg_analyzer and player_id and goalie_id:
        svg_stats = svg_analyzer.get_svg_stats(player_id, goalie_id)

    if svg_stats and svg_stats.get('is_confident'):
        # Confident SvG data - use it heavily
        svg_ppg = svg_stats['ppg_vs_goalie']

        # Normalize PPG: 0.5 avg, 1.5 elite → 0-1 scale
        svg_normalized = min(svg_ppg / 1.5, 1.0)

        # Combine SvG with goalie weakness
        matchup_score = (
            svg_normalized * SVG_WEIGHT +
            goalie_weakness * TEAM_DEFENSE_WEIGHT
        )

        return {
            'matchup_score': round(matchup_score, 4),
            'matchup_details': {
                'method': 'confident_svg',
                'svg_games': svg_stats['games_faced'],
                'svg_points': svg_stats['total_points'],
                'svg_ppg': svg_stats['ppg_vs_goalie'],
                'svg_normalized': round(svg_normalized, 4),
                'goalie_weakness_component': round(goalie_weakness * TEAM_DEFENSE_WEIGHT, 4),
            }
        }

    elif svg_stats:
        # Limited SvG data - use as supplementary
        svg_ppg = svg_stats['ppg_vs_goalie']
        svg_normalized = min(svg_ppg / 1.5, 1.0)

        # Blend with lower SvG weight
        limited_svg_weight = 0.30
        matchup_score = (
            svg_normalized * limited_svg_weight +
            goalie_weakness * (1 - limited_svg_weight)
        )

        return {
            'matchup_score': round(matchup_score, 4),
            'matchup_details': {
                'method': 'limited_svg',
                'svg_games': svg_stats['games_faced'],
                'svg_points': svg_stats['total_points'],
                'svg_ppg': svg_stats['ppg_vs_goalie'],
                'note': f"Only {svg_stats['games_faced']} games faced (need {MIN_SVG_GAMES} for confident)",
            }
        }

    else:
        # No SvG data - use goalie weakness as proxy
        return {
            'matchup_score': round(goalie_weakness, 4),
            'matchup_details': {
                'method': 'goalie_weakness_proxy',
                'note': 'No SvG history available',
            }
        }


def calculate_matchup_batch(
    players: List[Dict[str, Any]],
    svg_analyzer: Optional[SvGAnalyzer] = None
) -> List[Dict[str, Any]]:
    """
    Calculate matchup scores for a batch of players.

    Args:
        players: List of enriched player dictionaries
        svg_analyzer: SvGAnalyzer instance

    Returns:
        Players with matchup_score and matchup_details added
    """
    for player in players:
        result = calculate_matchup_score(player, svg_analyzer)
        player['matchup_score'] = result['matchup_score']
        player['matchup_details'] = result['matchup_details']

    return players


if __name__ == '__main__':
    # Test SvG analyzer
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env.local'))

    from providers.cached_provider import CachedNHLProvider

    print("=" * 70)
    print("SVG ANALYZER TEST")
    print("=" * 70)

    provider = CachedNHLProvider()
    analyzer = SvGAnalyzer(provider)

    # Build SvG from last 30 days
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    print(f"\nBuilding SvG history from {start_date} to {end_date}...")
    games = analyzer.build_svg_from_date_range(start_date, end_date)

    print(f"\nSummary: {analyzer.get_summary_stats()}")

    # Find some matchups with history
    confident_matchups = [
        (k, v) for k, v in analyzer.svg_history.items()
        if v['games'] >= MIN_SVG_GAMES
    ]

    print(f"\nConfident matchups found: {len(confident_matchups)}")

    if confident_matchups:
        print("\nSample confident matchups:")
        for (skater_id, goalie_id), data in list(confident_matchups)[:5]:
            ppg = data['points'] / data['games']
            print(f"  Skater {skater_id} vs Goalie {goalie_id}: "
                  f"{data['games']} games, {data['points']} pts ({ppg:.2f} PPG)")
