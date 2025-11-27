# nhl_isolated/providers/cached_provider.py
"""
Cached wrapper for NHL SportsDataIO provider.

Wraps all API calls with caching to reduce API usage during development.
Uses the CacheManager for TTL-based caching.
"""
import os
from datetime import date
from typing import List, Dict, Any, Optional

from providers.sportsdataio_nhl import SportsDataIONHLProvider
from utilities.cache_manager import CacheManager


class CachedNHLProvider:
    """
    Caching wrapper for SportsDataIONHLProvider.

    All API calls check cache first. If cache is fresh, returns cached data.
    If cache is stale or missing, fetches from API and caches result.

    Cache TTL values (in hours):
    - Schedule/Games: 1 hour
    - Starting Goalies: 0.5 hours (30 min)
    - Rosters: 24 hours
    - Line Combinations: 6 hours
    - Player Stats: 6 hours
    - Team Stats: 24 hours
    - Box Scores: 1 hour
    - Play-by-Play: 168 hours (7 days)
    """

    def __init__(self, api_key: Optional[str] = None, cache_dir: str = 'data/cache/'):
        """
        Initialize cached provider.

        Args:
            api_key: SportsDataIO API key (or from env).
            cache_dir: Directory for cache files.
        """
        self.provider = SportsDataIONHLProvider(api_key)
        self.cache = CacheManager(cache_dir)

        # Track API calls for monitoring
        self.api_calls = 0
        self.cache_hits = 0

    def _format_date(self, d: date) -> str:
        return d.strftime('%Y-%m-%d')

    def _log_cache_hit(self, cache_name: str):
        self.cache_hits += 1
        print(f"[Cache HIT] {cache_name}")

    def _log_api_call(self, endpoint: str):
        self.api_calls += 1
        print(f"[API CALL #{self.api_calls}] {endpoint}")

    def get_stats(self) -> Dict[str, int]:
        """Return cache/API call statistics."""
        return {
            'api_calls': self.api_calls,
            'cache_hits': self.cache_hits,
            'hit_rate': self.cache_hits / (self.api_calls + self.cache_hits) * 100
            if (self.api_calls + self.cache_hits) > 0 else 0
        }

    # =========================================================================
    # SCHEDULE & GAMES
    # =========================================================================

    def get_games_by_date(self, game_date: date, ttl_hours: float = 1.0) -> List[Dict[str, Any]]:
        """Fetch games with caching."""
        cache_name = f"games_{self._format_date(game_date)}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"games_by_date/{game_date}")
        data = self.provider.get_games_by_date(game_date)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_scores_basic(self, game_date: date, ttl_hours: float = 1.0) -> List[Dict[str, Any]]:
        """Fetch basic scores with caching."""
        cache_name = f"scores_basic_{self._format_date(game_date)}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"scores_basic/{game_date}")
        data = self.provider.get_scores_basic(game_date)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # GOALTENDERS
    # =========================================================================

    def get_starting_goaltenders(self, game_date: date, ttl_hours: float = 0.5) -> List[Dict[str, Any]]:
        """Fetch starting goalies with short TTL (timing dependent)."""
        cache_name = f"starting_goalies_{self._format_date(game_date)}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"starting_goaltenders/{game_date}")
        data = self.provider.get_starting_goaltenders(game_date)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_goalie_depth_charts(self, ttl_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Fetch goalie depth charts with caching."""
        cache_name = "goalie_depth_charts"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call("goalie_depth_charts")
        data = self.provider.get_goalie_depth_charts()
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # ROSTERS & PLAYERS
    # =========================================================================

    def get_team_roster(self, team: str, ttl_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Fetch team roster with caching."""
        cache_name = f"roster_{team}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"team_roster/{team}")
        data = self.provider.get_team_roster(team)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_active_players(self, ttl_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Fetch all active players with caching."""
        cache_name = "active_players"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call("active_players")
        data = self.provider.get_active_players()
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_all_teams(self, ttl_hours: float = 168.0) -> List[Dict[str, Any]]:
        """Fetch all teams with long TTL caching."""
        cache_name = "all_teams"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call("all_teams")
        data = self.provider.get_all_teams()
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # LINE COMBINATIONS
    # =========================================================================

    def get_line_combinations(self, season: str, ttl_hours: float = 6.0) -> List[Dict[str, Any]]:
        """Fetch line combinations with caching."""
        cache_name = f"line_combos_{season}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"line_combinations/{season}")
        data = self.provider.get_line_combinations(season)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # PLAYER STATISTICS
    # =========================================================================

    def get_player_season_stats(self, season: str, ttl_hours: float = 6.0) -> List[Dict[str, Any]]:
        """Fetch player season stats with caching."""
        cache_name = f"player_season_stats_{season}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"player_season_stats/{season}")
        data = self.provider.get_player_season_stats(season)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_player_game_logs(self, player_id: int, season: str,
                             num_games: int = 10, ttl_hours: float = 6.0) -> List[Dict[str, Any]]:
        """Fetch player game logs with caching."""
        cache_name = f"game_logs_{player_id}_{season}_{num_games}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"player_game_logs/{player_id}")
        data = self.provider.get_player_game_logs(player_id, season, num_games)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # TEAM STATISTICS
    # =========================================================================

    def get_team_season_stats(self, season: str, ttl_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Fetch team season stats with caching."""
        cache_name = f"team_season_stats_{season}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"team_season_stats/{season}")
        data = self.provider.get_team_season_stats(season)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_standings(self, season: str, ttl_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Fetch standings with caching."""
        cache_name = f"standings_{season}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"standings/{season}")
        data = self.provider.get_standings(season)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # BOX SCORES & SETTLEMENT
    # =========================================================================

    def get_box_scores_final(self, game_date: date, ttl_hours: float = 1.0) -> List[Dict[str, Any]]:
        """Fetch final box scores with caching."""
        cache_name = f"box_scores_{self._format_date(game_date)}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"box_scores_final/{game_date}")
        data = self.provider.get_box_scores_final(game_date)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_box_score_final(self, game_id: int, ttl_hours: float = 1.0) -> Dict[str, Any]:
        """Fetch single game box score with caching."""
        cache_name = f"box_score_{game_id}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"box_score_final/{game_id}")
        data = self.provider.get_box_score_final(game_id)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # PLAY-BY-PLAY
    # =========================================================================

    def get_play_by_play(self, game_id: int, ttl_hours: float = 168.0) -> Dict[str, Any]:
        """Fetch play-by-play with long TTL (historical data)."""
        cache_name = f"pbp_{game_id}"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call(f"play_by_play/{game_id}")
        data = self.provider.get_play_by_play(game_id)
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # =========================================================================
    # UTILITY
    # =========================================================================

    def get_current_season(self, ttl_hours: float = 24.0) -> Dict[str, Any]:
        """Fetch current season info with caching."""
        cache_name = "current_season"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call("current_season")
        data = self.provider.get_current_season()
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    def get_stadiums(self, ttl_hours: float = 168.0) -> List[Dict[str, Any]]:
        """Fetch stadiums with long TTL caching."""
        cache_name = "stadiums"

        cached = self.cache.get_if_fresh(cache_name, ttl_hours)
        if cached is not None:
            self._log_cache_hit(cache_name)
            return cached

        self._log_api_call("stadiums")
        data = self.provider.get_stadiums()
        self.cache.set_cache(cache_name, data, ttl_hours)
        return data

    # Direct pass-through for real-time checks (no caching)
    def are_any_games_in_progress(self) -> bool:
        """Check if games in progress (no caching - real-time)."""
        self._log_api_call("are_games_in_progress")
        return self.provider.are_any_games_in_progress()
