# nhl_isolated/providers/base.py
"""
Base provider class for NHL data sources.
Mirrors the MLB provider pattern for consistency.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import date


class NHLDataProvider(ABC):
    """
    Abstract base class for NHL data providers.

    All NHL data providers must implement these methods to ensure
    consistent data access patterns across the pipeline.
    """

    @abstractmethod
    def get_games_by_date(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch all NHL games scheduled for a given date.

        Args:
            game_date: The date to fetch games for.

        Returns:
            List of game dictionaries containing game details.
        """
        pass

    @abstractmethod
    def get_starting_goaltenders(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch confirmed/projected starting goaltenders for a given date.

        Args:
            game_date: The date to fetch goaltenders for.

        Returns:
            List of goaltender dictionaries with game assignments.
        """
        pass

    @abstractmethod
    def get_team_roster(self, team: str) -> List[Dict[str, Any]]:
        """
        Fetch the active roster for a given team.

        Args:
            team: Team abbreviation (e.g., 'EDM', 'TOR').

        Returns:
            List of player dictionaries for the team.
        """
        pass

    @abstractmethod
    def get_player_game_logs(self, player_id: int, season: str,
                             num_games: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch recent game logs for a player.

        Args:
            player_id: The player's unique identifier.
            season: Season string (e.g., '2025').
            num_games: Number of recent games to fetch.

        Returns:
            List of game log dictionaries.
        """
        pass

    @abstractmethod
    def get_player_season_stats(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch season statistics for all players.

        Args:
            season: Season string (e.g., '2025').

        Returns:
            List of player season stat dictionaries.
        """
        pass

    @abstractmethod
    def get_line_combinations(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch line combinations for all teams.

        Args:
            season: Season string (e.g., '2025').

        Returns:
            List of line combination dictionaries.
        """
        pass

    @abstractmethod
    def get_goalie_depth_charts(self) -> List[Dict[str, Any]]:
        """
        Fetch goalie depth charts for all teams.

        Returns:
            List of goalie depth chart entries.
        """
        pass

    @abstractmethod
    def get_team_season_stats(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch team-level season statistics (for defensive analysis).

        Args:
            season: Season string (e.g., '2025').

        Returns:
            List of team stat dictionaries.
        """
        pass

    @abstractmethod
    def get_box_scores_final(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch final box scores for games on a given date (for settlement).

        Args:
            game_date: The date to fetch box scores for.

        Returns:
            List of box score dictionaries.
        """
        pass

    @abstractmethod
    def get_play_by_play(self, game_id: int) -> Dict[str, Any]:
        """
        Fetch play-by-play data for a specific game.
        Used for skater-vs-goalie attribution.

        Args:
            game_id: The game's unique identifier.

        Returns:
            Play-by-play dictionary with all game events.
        """
        pass

    @abstractmethod
    def get_injuries(self) -> List[Dict[str, Any]]:
        """
        Fetch current injury list.

        Returns:
            List of injured player dictionaries.
        """
        pass

    @abstractmethod
    def get_transactions(self) -> List[Dict[str, Any]]:
        """
        Fetch recent transactions (callups, scratches, trades).

        Returns:
            List of transaction dictionaries.
        """
        pass

    # Optional methods with default implementations

    def get_current_season(self) -> Dict[str, Any]:
        """
        Fetch current season information.

        Returns:
            Dictionary with current season details.
        """
        raise NotImplementedError("Subclass must implement get_current_season()")

    def get_active_players(self) -> List[Dict[str, Any]]:
        """
        Fetch all active NHL players.

        Returns:
            List of active player dictionaries.
        """
        raise NotImplementedError("Subclass must implement get_active_players()")

    def get_all_teams(self) -> List[Dict[str, Any]]:
        """
        Fetch all NHL teams (including metadata).

        Returns:
            List of team dictionaries.
        """
        raise NotImplementedError("Subclass must implement get_all_teams()")
