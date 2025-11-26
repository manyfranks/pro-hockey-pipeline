# nhl_isolated/utilities/cache_manager.py
"""
Cache manager for the NHL ETL pipeline.
Mirrors the MLB cache_manager for consistency.

Handles reading, writing, and checking freshness of various cache files.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List


class CacheManager:
    """
    Manages caching for the NHL ETL pipeline to reduce redundant data fetching.

    Cache TTL Guidelines (from NHL_ALGORITHM_ADR.md):
    - Schedule/Games: 1 hour
    - Rosters: 24 hours
    - Starting Goalies: 30 minutes (frequent updates)
    - Line Combinations: 6 hours
    - Player Season Stats: 6 hours
    - Box Scores: 1 hour
    - Play-by-Play: 7 days (historical, rarely changes)
    - Team Stats: 24 hours
    - Injuries: 6 hours
    - Transactions: 6 hours
    """

    # Default TTL values in hours
    DEFAULT_TTL = {
        'games': 1,
        'scores_basic': 1,
        'starting_goalies': 0.5,  # 30 minutes
        'goalie_depth': 24,
        'roster': 24,
        'active_players': 24,
        'teams': 168,  # 1 week
        'line_combinations': 6,
        'player_season_stats': 6,
        'player_game_logs': 6,
        'team_season_stats': 24,
        'box_scores': 1,
        'play_by_play': 168,  # 7 days
        'injuries': 6,
        'transactions': 6,
        'standings': 24,
        'current_season': 24,
    }

    def __init__(self, cache_dir: str = 'data/cache/'):
        """
        Initialize the CacheManager.

        Args:
            cache_dir: The directory where cache files are stored.
        """
        # Handle relative paths from nhl_isolated directory
        if not os.path.isabs(cache_dir):
            # Get the nhl_isolated directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_dir = os.path.join(base_dir, cache_dir)

        self.cache_dir = cache_dir
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            print(f"[Cache] Created cache directory: {self.cache_dir}")

    def _get_cache_path(self, cache_name: str) -> str:
        """Construct the full path for a given cache file name."""
        return os.path.join(self.cache_dir, f"{cache_name}.json")

    def _get_cache_metadata_path(self, cache_name: str) -> str:
        """Construct the path for cache metadata (timestamps)."""
        return os.path.join(self.cache_dir, f"{cache_name}_meta.json")

    def get_cache(self, cache_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve data from a specified cache file.

        Args:
            cache_name: The name of the cache (e.g., 'games_2024-11-25').

        Returns:
            The cached data as a dictionary, or None if not found.
        """
        cache_path = self._get_cache_path(cache_name)
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[Cache] Error reading {cache_name}: {e}")
            return None

    def set_cache(self, cache_name: str, data: Any, ttl_hours: Optional[float] = None) -> None:
        """
        Write data to a specified cache file with timestamp metadata.

        Args:
            cache_name: The name of the cache.
            data: The data to be cached (dict, list, or other JSON-serializable).
            ttl_hours: Optional TTL override in hours.
        """
        cache_path = self._get_cache_path(cache_name)
        meta_path = self._get_cache_metadata_path(cache_name)

        try:
            # Write data
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            # Write metadata
            metadata = {
                'created_at': datetime.now().isoformat(),
                'ttl_hours': ttl_hours or self._infer_ttl(cache_name)
            }
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

        except IOError as e:
            print(f"[Cache] Error writing {cache_name}: {e}")

    def _infer_ttl(self, cache_name: str) -> float:
        """Infer TTL from cache name prefix."""
        for prefix, ttl in self.DEFAULT_TTL.items():
            if cache_name.startswith(prefix):
                return ttl
        return 6  # Default 6 hours

    def is_cache_stale(self, cache_name: str, max_age_hours: Optional[float] = None) -> bool:
        """
        Check if a cache file is older than its TTL.

        Args:
            cache_name: The name of the cache.
            max_age_hours: Optional override for max age in hours.

        Returns:
            True if the cache is stale or doesn't exist.
        """
        cache_path = self._get_cache_path(cache_name)
        meta_path = self._get_cache_metadata_path(cache_name)

        if not os.path.exists(cache_path):
            return True

        # Check metadata for TTL
        try:
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    metadata = json.load(f)
                created_at = datetime.fromisoformat(metadata['created_at'])
                ttl = max_age_hours or metadata.get('ttl_hours', self._infer_ttl(cache_name))
            else:
                # Fall back to file modification time
                created_at = datetime.fromtimestamp(os.path.getmtime(cache_path))
                ttl = max_age_hours or self._infer_ttl(cache_name)

            if datetime.now() - created_at > timedelta(hours=ttl):
                return True

        except (OSError, json.JSONDecodeError, KeyError) as e:
            print(f"[Cache] Error checking staleness for {cache_name}: {e}")
            return True

        return False

    def get_if_fresh(self, cache_name: str, max_age_hours: Optional[float] = None) -> Optional[Any]:
        """
        Get cached data only if it's not stale.

        Args:
            cache_name: The name of the cache.
            max_age_hours: Optional override for max age.

        Returns:
            Cached data if fresh, None if stale or missing.
        """
        if self.is_cache_stale(cache_name, max_age_hours):
            return None
        return self.get_cache(cache_name)

    def get_cached_item(self, cache_name: str, item_key: str) -> Optional[Any]:
        """
        Retrieve a specific item from a cache file (when cache is a dict).

        Args:
            cache_name: The name of the cache.
            item_key: The key of the item to retrieve.

        Returns:
            The value of the cached item, or None if not found.
        """
        cache_data = self.get_cache(cache_name)
        if cache_data and isinstance(cache_data, dict):
            return cache_data.get(item_key)
        return None

    def set_cached_item(self, cache_name: str, item_key: str, item_value: Any) -> None:
        """
        Set or update a specific item in a cache file.

        Args:
            cache_name: The name of the cache.
            item_key: The key of the item to set.
            item_value: The value to set.
        """
        cache_data = self.get_cache(cache_name) or {}
        cache_data[item_key] = item_value
        self.set_cache(cache_name, cache_data)

    def remove_cached_item(self, cache_name: str, item_key: str) -> bool:
        """
        Remove a specific item from a cache file.

        Returns:
            True if removed, False if it didn't exist.
        """
        cache_data = self.get_cache(cache_name)
        if cache_data and isinstance(cache_data, dict) and item_key in cache_data:
            del cache_data[item_key]
            self.set_cache(cache_name, cache_data)
            return True
        return False

    def cleanup_stale_files(self, max_age_days: int = 7) -> int:
        """
        Remove all cache files older than max_age_days.

        Args:
            max_age_days: Maximum age in days.

        Returns:
            Number of files removed.
        """
        print(f"[Cache] Cleaning up files older than {max_age_days} day(s)...")
        if not os.path.exists(self.cache_dir):
            return 0

        now = datetime.now()
        removed_count = 0

        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            if os.path.isfile(file_path):
                try:
                    file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if now - file_mod_time > timedelta(days=max_age_days):
                        os.remove(file_path)
                        print(f"[Cache] Removed stale file: {filename}")
                        removed_count += 1
                except OSError as e:
                    print(f"[Cache] Error processing {file_path}: {e}")

        print(f"[Cache] Cleanup complete. Removed {removed_count} files.")
        return removed_count

    def invalidate_settlement_cache(self, settlement_date: str) -> int:
        """
        Invalidate cache files related to settlement for a given date.

        Args:
            settlement_date: Date in YYYY-MM-DD format.

        Returns:
            Number of files invalidated.
        """
        print(f"[Cache] Invalidating settlement cache for {settlement_date}")

        patterns = [
            f"games_{settlement_date}",
            f"box_scores_{settlement_date}",
            f"starting_goalies_{settlement_date}",
            f"predictions_{settlement_date}",
        ]

        if not os.path.exists(self.cache_dir):
            return 0

        invalidated = 0
        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            if os.path.isfile(file_path):
                cache_name = filename.replace('.json', '')
                if any(cache_name.startswith(p) for p in patterns):
                    try:
                        os.remove(file_path)
                        print(f"[Cache] Invalidated: {filename}")
                        invalidated += 1
                    except OSError as e:
                        print(f"[Cache] Error removing {file_path}: {e}")

        print(f"[Cache] Invalidated {invalidated} settlement-related files.")
        return invalidated

    def list_caches(self) -> List[Dict[str, Any]]:
        """
        List all cache files with their metadata.

        Returns:
            List of cache info dictionaries.
        """
        caches = []
        if not os.path.exists(self.cache_dir):
            return caches

        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.json') and not filename.endswith('_meta.json'):
                cache_name = filename.replace('.json', '')
                file_path = os.path.join(self.cache_dir, filename)

                try:
                    mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    size = os.path.getsize(file_path)
                    is_stale = self.is_cache_stale(cache_name)

                    caches.append({
                        'name': cache_name,
                        'modified': mod_time.isoformat(),
                        'size_kb': round(size / 1024, 2),
                        'is_stale': is_stale
                    })
                except OSError:
                    pass

        return sorted(caches, key=lambda x: x['modified'], reverse=True)
