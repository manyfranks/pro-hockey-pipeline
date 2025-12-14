# nhl_isolated/providers/nhl_official_api.py
"""
NHL Official API Provider

Provides accurate, unscrambled data from the official NHL API (api-web.nhle.com).
This replaces SportsData.io for all statistical data.

Endpoints used:
- /v1/score/{date} - Daily game schedule
- /v1/gamecenter/{game_id}/boxscore - Box scores with player stats
- /v1/player/{player_id}/game-log/now - Player game logs (recent form)
- /v1/player/{player_id}/landing - Player season stats and info
- /v1/club-stats/{team}/now - Team roster with season stats
- /v1/roster/{team}/current - Team roster with player IDs
- /v1/goalie-stats-leaders/current - Goalie statistics

Data is 100% accurate - no scrambling like SportsData.io free tier.
"""

import os
import json
import time
import requests
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from utilities.logger import get_logger

logger = get_logger('nhl_api')


class NHLOfficialAPI:
    """Provider for NHL Official API data."""

    BASE_URL = "https://api-web.nhle.com"
    CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "nhl_official"
    CACHE_TTL_HOURS = 1  # Cache TTL for most data
    GAME_LOG_CACHE_TTL_HOURS = 6  # Game logs change less frequently

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the NHL API provider."""
        self.cache_dir = Path(cache_dir) if cache_dir else self.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; NHL-Analytics/1.0)',
            'Accept': 'application/json',
        })

    def _get_cached(self, cache_key: str, ttl_hours: float = None) -> Optional[Dict]:
        """Get data from cache if fresh."""
        ttl = ttl_hours or self.CACHE_TTL_HOURS
        cache_path = self.cache_dir / f"{cache_key}.json"

        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)

                cached_at = datetime.fromisoformat(cached.get('_cached_at', '2000-01-01'))
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)

                age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600

                if age_hours < ttl:
                    return cached.get('data')
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        return None

    def _set_cache(self, cache_key: str, data: Any) -> None:
        """Save data to cache."""
        cache_path = self.cache_dir / f"{cache_key}.json"

        cache_data = {
            '_cached_at': datetime.now(timezone.utc).isoformat(),
            'data': data,
        }

        with open(cache_path, 'w') as f:
            json.dump(cache_data, f)

    def _api_get(self, endpoint: str, cache_key: str = None, ttl_hours: float = None,
                 max_retries: int = 3, backoff_factor: float = 1.0) -> Optional[Dict]:
        """
        Make API request with optional caching and retry logic.

        Args:
            endpoint: API endpoint path
            cache_key: Key for caching response
            ttl_hours: Cache time-to-live in hours
            max_retries: Maximum number of retry attempts for transient failures
            backoff_factor: Multiplier for exponential backoff (wait = backoff_factor * 2^attempt)
        """
        # Check cache first
        if cache_key:
            cached = self._get_cached(cache_key, ttl_hours)
            if cached is not None:
                return cached

        # Make request with retries
        url = f"{self.BASE_URL}{endpoint}"
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=15)

                # Retry on 5xx server errors
                if response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"Server error {response.status_code}, retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    response.raise_for_status()

                # Retry on 429 rate limit
                if response.status_code == 429:
                    last_error = "Rate limited"
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor * (2 ** attempt) * 2  # Longer wait for rate limits
                        logger.warning(f"Rate limited, retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                data = response.json()

                # Cache the result
                if cache_key:
                    self._set_cache(cache_key, data)

                return data

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                if attempt < max_retries - 1:
                    wait_time = backoff_factor * (2 ** attempt)
                    logger.warning(f"Timeout, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                if attempt < max_retries - 1:
                    wait_time = backoff_factor * (2 ** attempt)
                    logger.warning(f"Connection error, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

            except requests.RequestException as e:
                last_error = str(e)
                # Don't retry on 4xx client errors (except 429)
                break

        logger.error(f"Request failed after {max_retries} attempts: {last_error}")
        return None

    # =========================================================================
    # SCHEDULE & GAMES
    # =========================================================================

    def get_games_by_date(self, game_date: date) -> List[Dict]:
        """
        Get all games for a specific date.

        Args:
            game_date: Date to get games for

        Returns:
            List of game dictionaries with teams, times, IDs
        """
        date_str = game_date.strftime('%Y-%m-%d')
        cache_key = f"schedule_{date_str}"

        data = self._api_get(f"/v1/score/{date_str}", cache_key, ttl_hours=0.5)

        if not data:
            return []

        games = data.get('games', [])

        # Normalize to consistent format
        normalized = []
        for game in games:
            normalized.append({
                'game_id': game.get('id'),
                'season': game.get('season'),
                'game_type': game.get('gameType'),
                'game_date': game.get('gameDate'),
                'start_time_utc': game.get('startTimeUTC'),
                'game_state': game.get('gameState'),
                'away_team': game.get('awayTeam', {}).get('abbrev'),
                'away_team_id': game.get('awayTeam', {}).get('id'),
                'away_score': game.get('awayTeam', {}).get('score'),
                'home_team': game.get('homeTeam', {}).get('abbrev'),
                'home_team_id': game.get('homeTeam', {}).get('id'),
                'home_score': game.get('homeTeam', {}).get('score'),
                'venue': game.get('venue', {}).get('default') if game.get('venue') else None,
            })

        return normalized

    def get_box_score(self, game_id: int) -> Optional[Dict]:
        """
        Get detailed box score for a game.

        Args:
            game_id: NHL game ID

        Returns:
            Box score with player stats for both teams
        """
        cache_key = f"boxscore_{game_id}"

        data = self._api_get(f"/v1/gamecenter/{game_id}/boxscore", cache_key, ttl_hours=24)

        if not data:
            return None

        # Extract player stats
        player_stats = data.get('playerByGameStats', {})

        result = {
            'game_id': game_id,
            'game_state': data.get('gameState'),
            'away_team': data.get('awayTeam', {}).get('abbrev'),
            'home_team': data.get('homeTeam', {}).get('abbrev'),
            'away_score': data.get('awayTeam', {}).get('score', 0),
            'home_score': data.get('homeTeam', {}).get('score', 0),
            'total_goals': data.get('awayTeam', {}).get('score', 0) + data.get('homeTeam', {}).get('score', 0),
            'players': [],
        }

        # Process both teams
        for team_key in ['awayTeam', 'homeTeam']:
            team_data = player_stats.get(team_key, {})
            team_abbrev = data.get(team_key, {}).get('abbrev')
            is_home = team_key == 'homeTeam'

            # Process forwards, defensemen, goalies
            for position_group in ['forwards', 'defense', 'goalies']:
                for player in team_data.get(position_group, []):
                    goals = player.get('goals', 0)
                    assists = player.get('assists', 0)
                    pp_goals = player.get('powerPlayGoals', 0)

                    player_info = {
                        'player_id': player.get('playerId'),
                        'name': player.get('name', {}).get('default'),
                        'team': team_abbrev,
                        'is_home': is_home,
                        'position': player.get('position'),
                        'goals': goals,
                        'assists': assists,
                        'points': goals + assists,
                        'toi': player.get('toi'),
                        'shots': player.get('sog', 0),
                        'blocked_shots': player.get('blockedShots', 0),
                        'hits': player.get('hits', 0),
                        'plus_minus': player.get('plusMinus', 0),
                        'pim': player.get('pim', 0),
                        'power_play_goals': pp_goals,
                        # Goalie-specific (use direct 'saves' field)
                        'saves': player.get('saves', 0),
                        'shots_against': player.get('shotsAgainst', 0),
                    }
                    result['players'].append(player_info)

        return result

    # =========================================================================
    # PLAYER STATS
    # =========================================================================

    def get_player_game_log(self, player_id: int, num_games: int = 10) -> List[Dict]:
        """
        Get recent game log for a player.

        Args:
            player_id: NHL player ID
            num_games: Number of recent games to return

        Returns:
            List of game log entries with goals, assists, etc.
        """
        cache_key = f"gamelog_{player_id}"

        data = self._api_get(f"/v1/player/{player_id}/game-log/now", cache_key,
                            ttl_hours=self.GAME_LOG_CACHE_TTL_HOURS)

        if not data:
            return []

        logs = data.get('gameLog', [])[:num_games]

        # Normalize
        normalized = []
        for log in logs:
            normalized.append({
                'game_id': log.get('gameId'),
                'game_date': log.get('gameDate'),
                'opponent': log.get('opponentAbbrev'),
                'home_away': 'home' if log.get('homeRoadFlag') == 'H' else 'away',
                'goals': log.get('goals', 0),
                'assists': log.get('assists', 0),
                'points': log.get('points', 0),
                'plus_minus': log.get('plusMinus', 0),
                'pim': log.get('pim', 0),
                'shots': log.get('shots', 0),
                'toi': log.get('toi'),
                'pp_goals': log.get('powerPlayGoals', 0),
                'pp_points': log.get('powerPlayPoints', 0),
            })

        return normalized

    def get_player_info(self, player_id: int) -> Optional[Dict]:
        """
        Get detailed player information and season stats.

        Args:
            player_id: NHL player ID

        Returns:
            Player info including season stats
        """
        cache_key = f"player_{player_id}"

        data = self._api_get(f"/v1/player/{player_id}/landing", cache_key, ttl_hours=6)

        if not data:
            return None

        # Extract season stats
        featured = data.get('featuredStats', {})
        regular_season = featured.get('regularSeason', {}).get('subSeason', {})

        return {
            'player_id': data.get('playerId'),
            'name': f"{data.get('firstName', {}).get('default', '')} {data.get('lastName', {}).get('default', '')}".strip(),
            'first_name': data.get('firstName', {}).get('default'),
            'last_name': data.get('lastName', {}).get('default'),
            'team': data.get('currentTeamAbbrev'),
            'team_id': data.get('currentTeamId'),
            'position': data.get('position'),
            'jersey_number': data.get('sweaterNumber'),
            'shoots_catches': data.get('shootsCatches'),
            'height_inches': data.get('heightInInches'),
            'weight_pounds': data.get('weightInPounds'),
            'birth_date': data.get('birthDate'),
            'birth_country': data.get('birthCountry'),
            # Season stats
            'season_games': regular_season.get('gamesPlayed', 0),
            'season_goals': regular_season.get('goals', 0),
            'season_assists': regular_season.get('assists', 0),
            'season_points': regular_season.get('points', 0),
            'season_plus_minus': regular_season.get('plusMinus', 0),
            'season_pim': regular_season.get('pim', 0),
            'season_pp_goals': regular_season.get('powerPlayGoals', 0),
            'season_pp_points': regular_season.get('powerPlayPoints', 0),
            'season_shots': regular_season.get('shots', 0),
            'season_toi_per_game': regular_season.get('avgToi'),
            # Goalie stats (if applicable)
            'goalie_gaa': regular_season.get('goalsAgainstAvg'),
            'goalie_sv_pct': regular_season.get('savePctg'),
            'goalie_wins': regular_season.get('wins'),
            'goalie_losses': regular_season.get('losses'),
            'goalie_otl': regular_season.get('otLosses'),
            'goalie_shutouts': regular_season.get('shutouts'),
        }

    # =========================================================================
    # TEAM DATA
    # =========================================================================

    def get_team_roster(self, team_abbrev: str) -> List[Dict]:
        """
        Get current roster for a team.

        Args:
            team_abbrev: Team abbreviation (e.g., 'EDM')

        Returns:
            List of players with IDs and positions
        """
        cache_key = f"roster_{team_abbrev}"

        data = self._api_get(f"/v1/roster/{team_abbrev}/current", cache_key, ttl_hours=24)

        if not data:
            return []

        roster = []
        for position_group in ['forwards', 'defensemen', 'goalies']:
            for player in data.get(position_group, []):
                roster.append({
                    'player_id': player.get('id'),
                    'name': f"{player.get('firstName', {}).get('default', '')} {player.get('lastName', {}).get('default', '')}".strip(),
                    'first_name': player.get('firstName', {}).get('default'),
                    'last_name': player.get('lastName', {}).get('default'),
                    'position': player.get('positionCode'),
                    'jersey_number': player.get('sweaterNumber'),
                    'shoots_catches': player.get('shootsCatches'),
                })

        return roster

    def get_team_stats(self, team_abbrev: str) -> Dict[str, List[Dict]]:
        """
        Get season stats for all players on a team.

        Args:
            team_abbrev: Team abbreviation

        Returns:
            Dict with 'skaters' and 'goalies' lists
        """
        cache_key = f"teamstats_{team_abbrev}"

        data = self._api_get(f"/v1/club-stats/{team_abbrev}/now", cache_key, ttl_hours=2)

        if not data:
            return {'skaters': [], 'goalies': []}

        skaters = []
        for player in data.get('skaters', []):
            skaters.append({
                'player_id': player.get('playerId'),
                'name': f"{player.get('firstName', {}).get('default', '')} {player.get('lastName', {}).get('default', '')}".strip(),
                'position': player.get('positionCode'),
                'games_played': player.get('gamesPlayed', 0),
                'goals': player.get('goals', 0),
                'assists': player.get('assists', 0),
                'points': player.get('points', 0),
                'plus_minus': player.get('plusMinus', 0),
                'pim': player.get('penaltyMinutes', 0),
                'pp_goals': player.get('powerPlayGoals', 0),
                'sh_goals': player.get('shorthandedGoals', 0),
                'shots': player.get('shots', 0),
                'shooting_pct': player.get('shootingPctg', 0),
                'avg_toi': player.get('avgTimeOnIcePerGame', 0) / 60 if player.get('avgTimeOnIcePerGame') else 0,  # Convert seconds to minutes
                'faceoff_pct': player.get('faceoffWinPctg'),
            })

        goalies = []
        for player in data.get('goalies', []):
            goalies.append({
                'player_id': player.get('playerId'),
                'name': f"{player.get('firstName', {}).get('default', '')} {player.get('lastName', {}).get('default', '')}".strip(),
                'games_played': player.get('gamesPlayed', 0),
                'games_started': player.get('gamesStarted', 0),
                'wins': player.get('wins', 0),
                'losses': player.get('losses', 0),
                'otl': player.get('overtimeLosses', 0),
                'save_pct': player.get('savePercentage', player.get('savePctg', 0)),  # Try both field names
                'gaa': player.get('goalsAgainstAverage', 0),
                'shutouts': player.get('shutouts', 0),
                'goals_against': player.get('goalsAgainst', 0),
                'saves': player.get('saves', 0),
                'shots_against': player.get('shotsAgainst', 0),
            })

        return {'skaters': skaters, 'goalies': goalies}

    # =========================================================================
    # GOALIE DATA
    # =========================================================================

    def get_goalie_stats(self, player_id: int) -> Optional[Dict]:
        """
        Get detailed goalie stats.

        Args:
            player_id: NHL goalie ID

        Returns:
            Goalie statistics
        """
        info = self.get_player_info(player_id)
        if not info:
            return None

        return {
            'player_id': info['player_id'],
            'name': info['name'],
            'team': info['team'],
            'games_played': info.get('season_games', 0),
            'gaa': info.get('goalie_gaa', 0),
            'save_pct': info.get('goalie_sv_pct', 0),
            'wins': info.get('goalie_wins', 0),
            'losses': info.get('goalie_losses', 0),
            'otl': info.get('goalie_otl', 0),
            'shutouts': info.get('goalie_shutouts', 0),
        }

    def get_probable_goalie(self, team_abbrev: str) -> Optional[Dict]:
        """
        Get the probable starting goalie for a team.

        Note: NHL API doesn't provide this directly. We use the goalie
        with more recent starts or fall back to the one with more games.

        Args:
            team_abbrev: Team abbreviation

        Returns:
            Goalie info dict or None
        """
        team_stats = self.get_team_stats(team_abbrev)
        goalies = team_stats.get('goalies', [])

        if not goalies:
            return None

        # Sort by games started, then games played
        goalies.sort(key=lambda g: (g.get('games_started', 0), g.get('games_played', 0)), reverse=True)

        starter = goalies[0]
        return {
            'player_id': starter['player_id'],
            'name': starter['name'],
            'team': team_abbrev,
            'gaa': starter.get('gaa', 0),
            'save_pct': starter.get('save_pct', 0),
            'games_played': starter.get('games_played', 0),
            'games_started': starter.get('games_started', 0),
            'is_confirmed': False,  # We're inferring, not confirmed
        }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def calculate_recent_form(self, player_id: int, num_games: int = 10) -> Dict:
        """
        Calculate recent form metrics for a player.

        Args:
            player_id: NHL player ID
            num_games: Number of games to analyze

        Returns:
            Dict with PPG, goals, assists, point streak, etc.
        """
        logs = self.get_player_game_log(player_id, num_games)

        if not logs:
            return {
                'recent_games': 0,
                'recent_goals': 0,
                'recent_assists': 0,
                'recent_points': 0,
                'recent_ppg': 0.0,
                'point_streak': 0,
            }

        total_goals = sum(log['goals'] for log in logs)
        total_assists = sum(log['assists'] for log in logs)
        total_points = total_goals + total_assists
        games = len(logs)

        # Calculate point streak (consecutive games with a point)
        streak = 0
        for log in logs:
            if log['points'] > 0:
                streak += 1
            else:
                break

        return {
            'recent_games': games,
            'recent_goals': total_goals,
            'recent_assists': total_assists,
            'recent_points': total_points,
            'recent_ppg': round(total_points / games, 3) if games > 0 else 0.0,
            'point_streak': streak,
            'recent_pp_goals': sum(log.get('pp_goals', 0) for log in logs),
            'recent_pp_points': sum(log.get('pp_points', 0) for log in logs),
        }

    def get_players_for_game(self, game_date: date, team_abbrev: str) -> List[Dict]:
        """
        Get all players for a team playing on a specific date with their stats.

        Args:
            game_date: Date of the game
            team_abbrev: Team abbreviation

        Returns:
            List of players with season stats and recent form
        """
        # Get team roster and stats
        team_stats = self.get_team_stats(team_abbrev)
        skaters = team_stats.get('skaters', [])

        players = []
        for skater in skaters:
            player_id = skater['player_id']

            # Get recent form
            recent = self.calculate_recent_form(player_id, 10)

            players.append({
                'player_id': player_id,
                'name': skater['name'],
                'team': team_abbrev,
                'position': skater['position'],
                'season_games': skater.get('games_played', 0),
                'season_goals': skater.get('goals', 0),
                'season_assists': skater.get('assists', 0),
                'season_points': skater.get('points', 0),
                'season_plus_minus': skater.get('plus_minus', 0),
                'season_pp_goals': skater.get('pp_goals', 0),
                'avg_toi_minutes': skater.get('avg_toi', 0),
                **recent,
            })

        return players


def main():
    """Test the NHL API provider."""
    api = NHLOfficialAPI()

    # Test 1: Get today's games
    print("=" * 70)
    print("TEST 1: Today's Games")
    print("=" * 70)

    today = date.today()
    games = api.get_games_by_date(today)
    print(f"Games on {today}: {len(games)}")
    for game in games:
        print(f"  {game['away_team']} @ {game['home_team']} ({game['game_state']})")

    # Test 2: Player game log
    print("\n" + "=" * 70)
    print("TEST 2: McDavid Game Log")
    print("=" * 70)

    mcdavid_id = 8478402
    logs = api.get_player_game_log(mcdavid_id, 5)
    print(f"Last {len(logs)} games:")
    for log in logs:
        print(f"  {log['game_date']} vs {log['opponent']}: {log['goals']}G, {log['assists']}A")

    # Test 3: Recent form calculation
    print("\n" + "=" * 70)
    print("TEST 3: Recent Form")
    print("=" * 70)

    form = api.calculate_recent_form(mcdavid_id, 10)
    print(f"McDavid last 10 games:")
    print(f"  {form['recent_goals']}G, {form['recent_assists']}A = {form['recent_points']} pts")
    print(f"  PPG: {form['recent_ppg']}")
    print(f"  Point streak: {form['point_streak']}")

    # Test 4: Team stats
    print("\n" + "=" * 70)
    print("TEST 4: EDM Team Stats (Top 5)")
    print("=" * 70)

    edm_stats = api.get_team_stats('EDM')
    skaters = sorted(edm_stats['skaters'], key=lambda x: x['points'], reverse=True)[:5]
    for s in skaters:
        print(f"  {s['name']}: {s['goals']}G, {s['assists']}A, {s['points']}pts, TOI: {s['avg_toi']:.1f}min")

    # Test 5: Goalie stats
    print("\n" + "=" * 70)
    print("TEST 5: EDM Goalies")
    print("=" * 70)

    for g in edm_stats['goalies']:
        print(f"  {g['name']}: {g['gaa']:.2f} GAA, {g['save_pct']:.3f} SV%, {g['wins']}W")


if __name__ == '__main__':
    main()
