# nhl_isolated/providers/sportsdataio_nhl.py
"""
SportsDataIO Provider for NHL data.

IMPORTANT: Free trial accounts receive "scrambled" data where statistical values
are randomly adjusted by 5-20% from actual values. This affects:
- Game statistics (goals, assists, saves, etc.)
- Performance metrics
- Settlement logic must use rounding to interpret scrambled values

Paid subscriptions provide unscrambled, accurate data.

API Documentation: https://sportsdata.io/developers/api-documentation/nhl
"""
import os
import requests
from typing import List, Dict, Any, Optional
from datetime import date, datetime
from nhl_isolated.providers.base import NHLDataProvider


class SportsDataIONHLProvider(NHLDataProvider):
    """
    SportsDataIO provider for NHL data.

    Implements all required endpoints for the NHL Player Points algorithm.
    Mirrors the MLB provider pattern for consistency across the analytics-pro platform.
    """

    BASE_URL = "https://api.sportsdata.io/v3/nhl"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the provider with an API key.

        Args:
            api_key: SportsDataIO API key. If not provided, reads from
                     SPORTS_DATA_API_KEY environment variable.
        """
        self.api_key = api_key or os.getenv('SPORTS_DATA_API_KEY')
        if not self.api_key:
            raise ValueError(
                "API key required. Set SPORTS_DATA_API_KEY environment variable "
                "or pass api_key parameter."
            )

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """
        Make a request to the SportsDataIO API.

        Args:
            endpoint: API endpoint path (e.g., '/scores/json/GamesByDate/2024-11-25')
            params: Optional query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            requests.exceptions.HTTPError: For HTTP errors.
        """
        url = f"{self.BASE_URL}{endpoint}"
        request_params = {'key': self.api_key}
        if params:
            request_params.update(params)

        response = requests.get(url, params=request_params)
        response.raise_for_status()
        return response.json()

    def _format_date(self, game_date: date) -> str:
        """Format date for API requests."""
        return game_date.strftime('%Y-%m-%d')

    # =========================================================================
    # SCHEDULE & GAMES
    # =========================================================================

    def get_games_by_date(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch all NHL games scheduled for a given date.

        Endpoint: /v3/nhl/scores/json/GamesByDate/{date}

        Args:
            game_date: The date to fetch games for.

        Returns:
            List of game dictionaries containing:
            - GameID, DateTime, Status
            - HomeTeam, AwayTeam
            - HomeTeamScore, AwayTeamScore (if completed)
            - StadiumID, Channel
        """
        formatted_date = self._format_date(game_date)
        endpoint = f"/scores/json/GamesByDate/{formatted_date}"

        try:
            games = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(games)} games for {formatted_date}")
            return games
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[NHL] No games found for {formatted_date} (404)")
                return []
            raise

    def get_scores_basic(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch lightweight schedule/scores for a given date.

        Endpoint: /v3/nhl/scores/json/ScoresBasic/{date}

        More efficient than GamesByDate when you only need basic info.
        """
        formatted_date = self._format_date(game_date)
        endpoint = f"/scores/json/ScoresBasic/{formatted_date}"

        try:
            scores = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(scores)} basic scores for {formatted_date}")
            return scores
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return []
            raise

    # =========================================================================
    # GOALTENDERS
    # =========================================================================

    def get_starting_goaltenders(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch confirmed/projected starting goaltenders for a given date.

        Endpoint: /v3/nhl/scores/json/StartingGoaltendersByDate/{date}

        This is critical for the goalie weakness component of scoring.
        Updates throughout the day as teams confirm starters.

        Returns:
            List of goaltender entries with:
            - PlayerID, Name, Team
            - GameID, Opponent
            - Confirmed (boolean)
        """
        formatted_date = self._format_date(game_date)
        endpoint = f"/scores/json/StartingGoaltendersByDate/{formatted_date}"

        try:
            goalies = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(goalies)} starting goaltenders for {formatted_date}")
            return goalies
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[NHL] No starting goaltenders found for {formatted_date}")
                return []
            raise

    def get_goalie_depth_charts(self) -> List[Dict[str, Any]]:
        """
        Fetch goalie depth charts for all teams.

        Endpoint: /v3/nhl/scores/json/DepthCharts_Goalies

        Used to identify backup goalies and callups.
        """
        endpoint = "/scores/json/DepthCharts_Goalies"

        try:
            depth_charts = self._make_request(endpoint)
            print(f"[NHL] Fetched goalie depth charts ({len(depth_charts)} entries)")
            return depth_charts
        except requests.exceptions.HTTPError:
            print("[NHL] Error fetching goalie depth charts")
            return []

    # =========================================================================
    # ROSTERS & PLAYERS
    # =========================================================================

    def get_team_roster(self, team: str) -> List[Dict[str, Any]]:
        """
        Fetch the active roster for a given team.

        Endpoint: /v3/nhl/scores/json/PlayersBasic/{team}

        Args:
            team: Team abbreviation (e.g., 'EDM', 'TOR', 'NYR').

        Returns:
            List of player dictionaries with:
            - PlayerID, FirstName, LastName
            - Position, Jersey, Team
            - Status, InjuryStatus
        """
        endpoint = f"/scores/json/PlayersBasic/{team}"

        try:
            roster = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(roster)} players for {team}")
            return roster
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching roster for {team}: {e}")
            return []

    def get_active_players(self) -> List[Dict[str, Any]]:
        """
        Fetch all active NHL players.

        Endpoint: /v3/nhl/scores/json/PlayersByActive
        """
        endpoint = "/scores/json/PlayersByActive"

        try:
            players = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(players)} active players")
            return players
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching active players: {e}")
            return []

    def get_all_teams(self) -> List[Dict[str, Any]]:
        """
        Fetch all NHL teams.

        Endpoint: /v3/nhl/scores/json/AllTeams
        """
        endpoint = "/scores/json/AllTeams"

        try:
            teams = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(teams)} teams")
            return teams
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching teams: {e}")
            return []

    # =========================================================================
    # LINE COMBINATIONS
    # =========================================================================

    def get_line_combinations(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch line combinations for all teams.

        Endpoint: /v3/nhl/stats/json/LinesBySeason/{season}
        (Note: This is under /stats/, not /scores/)

        Critical for line opportunity scoring component.
        Returns forward lines, defense pairings, and special teams units.

        Args:
            season: Season string (e.g., '2025', '2024').

        Returns:
            List of line combination entries with:
            - Team, LineNumber, LineType (EV, PP, SH)
            - Player1ID, Player2ID, Player3ID (for forward lines)
        """
        endpoint = f"/stats/json/LinesBySeason/{season}"

        try:
            lines = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(lines)} line combinations for {season}")
            return lines
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching line combinations: {e}")
            return []

    # =========================================================================
    # PLAYER STATISTICS
    # =========================================================================

    def get_player_season_stats(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch season statistics for all players.

        Endpoint: /v3/nhl/stats/json/PlayerSeasonStats/{season}

        Args:
            season: Season string (e.g., '2025').

        Returns:
            List of player stat dictionaries with:
            - PlayerID, Name, Team, Position
            - Games, Goals, Assists, Points
            - PlusMinus, PenaltyMinutes
            - PowerPlayGoals, PowerPlayAssists
            - ShortHandedGoals, ShortHandedAssists
            - For goalies: Wins, Losses, SavePercentage, GoalsAgainstAverage
        """
        endpoint = f"/stats/json/PlayerSeasonStats/{season}"

        try:
            stats = self._make_request(endpoint)
            print(f"[NHL] Fetched season stats for {len(stats)} players ({season})")
            return stats
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching player season stats: {e}")
            return []

    def get_player_game_logs(self, player_id: int, season: str,
                             num_games: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch recent game logs for a player.

        Endpoint: /v3/nhl/stats/json/PlayerGameStatsBySeason/{season}/{playerid}/{numgames}

        Critical for recent form calculation.

        Args:
            player_id: The player's unique identifier.
            season: Season string (e.g., '2025').
            num_games: Number of recent games to fetch.

        Returns:
            List of game log dictionaries with:
            - GameID, DateTime, Opponent, HomeOrAway
            - Goals, Assists, Points
            - PlusMinus, Shots, TimeOnIce
            - PowerPlayGoals, PowerPlayAssists
        """
        endpoint = f"/stats/json/PlayerGameStatsBySeason/{season}/{player_id}/{num_games}"

        try:
            logs = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(logs)} game logs for player {player_id}")
            return logs
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[NHL] No game logs found for player {player_id}")
                return []
            print(f"[NHL] Error fetching game logs for player {player_id}: {e}")
            return []

    # =========================================================================
    # TEAM STATISTICS
    # =========================================================================

    def get_team_season_stats(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch team-level season statistics.

        Endpoint: /v3/nhl/stats/json/TeamSeasonStats/{season}

        Used for defensive analysis (goals against, PK%, etc.).

        Args:
            season: Season string (e.g., '2025').

        Returns:
            List of team stat dictionaries with:
            - TeamID, Team, Name
            - Wins, Losses, OvertimeLosses
            - GoalsFor, GoalsAgainst
            - PowerPlayPercentage, PenaltyKillPercentage
        """
        endpoint = f"/stats/json/TeamSeasonStats/{season}"

        try:
            stats = self._make_request(endpoint)
            print(f"[NHL] Fetched team season stats for {len(stats)} teams ({season})")
            return stats
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching team season stats: {e}")
            return []

    # =========================================================================
    # BOX SCORES & SETTLEMENT
    # =========================================================================

    def get_box_scores_final(self, game_date: date) -> List[Dict[str, Any]]:
        """
        Fetch final box scores for games on a given date.

        Endpoint: /v3/nhl/stats/json/BoxScoresFinal/{date}

        Used for settlement - determining point outcomes.

        Args:
            game_date: The date to fetch box scores for.

        Returns:
            List of box score dictionaries with:
            - Game metadata
            - PlayerGames: List of player stats for the game
            - TeamGames: Team-level stats
        """
        formatted_date = self._format_date(game_date)
        endpoint = f"/stats/json/BoxScoresFinal/{formatted_date}"

        try:
            box_scores = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(box_scores)} final box scores for {formatted_date}")
            return box_scores
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[NHL] No final box scores for {formatted_date}")
                return []
            raise

    def get_box_score_final(self, game_id: int) -> Dict[str, Any]:
        """
        Fetch final box score for a specific game.

        Endpoint: /v3/nhl/stats/json/BoxScoreFinal/{gameid}
        """
        endpoint = f"/stats/json/BoxScoreFinal/{game_id}"

        try:
            box_score = self._make_request(endpoint)
            print(f"[NHL] Fetched box score for game {game_id}")
            return box_score
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching box score for game {game_id}: {e}")
            return {}

    # =========================================================================
    # PLAY-BY-PLAY (for Skater-vs-Goalie analysis)
    # =========================================================================

    def get_play_by_play(self, game_id: int, final_only: bool = True) -> Dict[str, Any]:
        """
        Fetch play-by-play data for a specific game.

        Endpoints:
        - Final: /v3/nhl/pbp/json/PlayByPlayFinal/{gameid} (completed games)
        - Live:  /v3/nhl/pbp/json/PlayByPlay/{gameid} (live + final)

        Used for precise skater-vs-goalie attribution.
        Each goal/assist can be attributed to the goalie on ice at that time.

        Args:
            game_id: The game's unique identifier.
            final_only: If True, use PlayByPlayFinal endpoint (default).
                       If False, use PlayByPlay endpoint (includes live games).

        Returns:
            Play-by-play dictionary with:
            - Game: Game metadata
            - Plays: List of play events
            - ScoringPlays: List of goals with scorer/assists
            - Penalties: List of penalties
            - Periods: Period summaries
        """
        if final_only:
            endpoint = f"/pbp/json/PlayByPlayFinal/{game_id}"
        else:
            endpoint = f"/pbp/json/PlayByPlay/{game_id}"

        try:
            pbp = self._make_request(endpoint)
            print(f"[NHL] Fetched play-by-play for game {game_id}")
            return pbp
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching play-by-play for game {game_id}: {e}")
            return {}

    # =========================================================================
    # INJURIES & TRANSACTIONS
    # =========================================================================

    def get_injuries(self) -> List[Dict[str, Any]]:
        """
        Fetch current injury list.

        Endpoint: /v3/nhl/scores/json/PlayerDetailsByInjured

        Returns:
            List of injured player dictionaries with:
            - PlayerID, Name, Team, Position
            - InjuryStatus, InjuryBodyPart, InjuryNotes
        """
        endpoint = "/scores/json/PlayerDetailsByInjured"

        try:
            injuries = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(injuries)} injured players")
            return injuries
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching injuries: {e}")
            return []

    def get_transactions(self) -> List[Dict[str, Any]]:
        """
        Fetch recent transactions.

        Endpoint: /v3/nhl/scores/json/Transactions

        Includes callups, demotions, trades, scratches.
        """
        endpoint = "/scores/json/Transactions"

        try:
            transactions = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(transactions)} transactions")
            return transactions
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching transactions: {e}")
            return []

    # =========================================================================
    # UTILITY ENDPOINTS
    # =========================================================================

    def get_current_season(self) -> Dict[str, Any]:
        """
        Fetch current season information.

        Endpoint: /v3/nhl/scores/json/CurrentSeason
        """
        endpoint = "/scores/json/CurrentSeason"

        try:
            season = self._make_request(endpoint)
            print(f"[NHL] Current season: {season}")
            return season
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching current season: {e}")
            return {}

    def get_standings(self, season: str) -> List[Dict[str, Any]]:
        """
        Fetch standings for a season.

        Endpoint: /v3/nhl/scores/json/Standings/{season}
        """
        endpoint = f"/scores/json/Standings/{season}"

        try:
            standings = self._make_request(endpoint)
            print(f"[NHL] Fetched standings for {season} ({len(standings)} teams)")
            return standings
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching standings: {e}")
            return []

    def are_any_games_in_progress(self) -> bool:
        """
        Check if any games are currently in progress.

        Endpoint: /v3/nhl/scores/json/AreAnyGamesInProgress
        """
        endpoint = "/scores/json/AreAnyGamesInProgress"

        try:
            result = self._make_request(endpoint)
            return result
        except requests.exceptions.HTTPError:
            return False

    def get_stadiums(self) -> List[Dict[str, Any]]:
        """
        Fetch all NHL stadiums/arenas.

        Endpoint: /v3/nhl/scores/json/Stadiums
        """
        endpoint = "/scores/json/Stadiums"

        try:
            stadiums = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(stadiums)} stadiums")
            return stadiums
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching stadiums: {e}")
            return []

    # =========================================================================
    # PLAYER NEWS (for context)
    # =========================================================================

    def get_player_news(self, player_id: int) -> List[Dict[str, Any]]:
        """
        Fetch news for a specific player.

        Endpoint: /v3/nhl/scores/json/PlayerNews/{playerid}

        Useful for injury updates, lineup changes.
        """
        endpoint = f"/scores/json/PlayerNews/{player_id}"

        try:
            news = self._make_request(endpoint)
            print(f"[NHL] Fetched {len(news)} news items for player {player_id}")
            return news
        except requests.exceptions.HTTPError as e:
            print(f"[NHL] Error fetching news for player {player_id}: {e}")
            return []
