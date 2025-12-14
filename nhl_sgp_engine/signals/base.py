"""
Base Signal Classes for NHL SGP Engine

Defines the abstract interface for all signals.
Matches the NFL/NCAAF signal framework.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class SignalResult:
    """
    Universal signal output.

    Attributes:
        signal_type: One of 'line_value', 'trend', 'usage', 'matchup', 'environment', 'correlation'
        strength: -1.0 to +1.0 (negative=under, positive=over)
        confidence: 0.0 to 1.0 (how reliable is this signal)
        evidence: Human-readable explanation
        raw_data: Supporting data for debugging
    """
    signal_type: str
    strength: float
    confidence: float
    evidence: str
    raw_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage."""
        return {
            'evidence': self.evidence,
            'strength': round(self.strength, 3),
            'confidence': round(self.confidence, 2),
        }


class BaseSignal(ABC):
    """Abstract base for all NHL SGP signals."""

    @property
    @abstractmethod
    def signal_type(self) -> str:
        """Return signal type identifier."""
        pass

    @abstractmethod
    def calculate(
        self,
        player_id: int,
        player_name: str,
        stat_type: str,
        line: float,
        game_context: Dict[str, Any],
    ) -> SignalResult:
        """
        Calculate signal for a specific prop.

        Args:
            player_id: NHL player ID
            player_name: Player's full name
            stat_type: 'points', 'goals', 'assists', etc.
            line: The prop line (e.g., 0.5, 1.5)
            game_context: Game info (opponent, date, home/away, etc.)

        Returns:
            SignalResult with strength, confidence, and evidence
        """
        pass


@dataclass
class PropContext:
    """
    Context for a player prop being evaluated.

    ARCHITECTURE (per MULTI_LEAGUE_ARCHITECTURE.md):
    - PRIMARY data: NHLDataProvider (NHL Official API)
    - SUPPLEMENTAL: Pipeline (is_scoreable, rank, line deployment)

    The SGP engine should be able to function with just NHL API data.
    Pipeline context is a BONUS that adds value for points props.
    """
    # =========================================================================
    # PROP DETAILS (required)
    # =========================================================================
    player_id: int
    player_name: str
    team: str
    position: str
    stat_type: str
    line: float

    # =========================================================================
    # GAME CONTEXT (required)
    # =========================================================================
    game_id: str
    game_date: str
    opponent: str
    is_home: bool

    # =========================================================================
    # PRIMARY DATA - From NHL API (NHLDataProvider)
    # =========================================================================
    # Season stats (from NHL API)
    season_games: Optional[int] = None
    season_points: Optional[float] = None
    season_goals: Optional[float] = None
    season_assists: Optional[float] = None
    season_shots: Optional[int] = None
    season_avg: Optional[float] = None  # Pre-calculated for stat_type

    # Recent form (from NHL API)
    recent_games: Optional[int] = None
    recent_ppg: Optional[float] = None
    recent_avg: Optional[float] = None  # Pre-calculated for stat_type
    point_streak: Optional[int] = None
    trend_direction: Optional[int] = None  # -1=cold, 0=stable, +1=hot
    trend_pct: Optional[float] = None

    # TOI (from NHL API)
    avg_toi_minutes: Optional[float] = None

    # Goalie matchup (from NHL API)
    opposing_goalie_id: Optional[int] = None
    opposing_goalie_name: Optional[str] = None
    opposing_goalie_sv_pct: Optional[float] = None
    opposing_goalie_gaa: Optional[float] = None
    goalie_confirmed: Optional[bool] = None

    # Opponent defense (from NHL API)
    opponent_ga_per_game: Optional[float] = None
    opponent_sa_per_game: Optional[float] = None

    # =========================================================================
    # SUPPLEMENTAL DATA - From Pipeline (optional, adds value for points)
    # =========================================================================
    # Pipeline scores (SUPPLEMENTAL)
    pipeline_score: Optional[float] = None
    pipeline_confidence: Optional[str] = None
    pipeline_rank: Optional[int] = None
    is_scoreable: Optional[bool] = None  # Key filter for points props

    # Line deployment (SUPPLEMENTAL - from DailyFaceoff via pipeline)
    line_number: Optional[int] = None  # 1-4 for even strength
    pp_unit: Optional[int] = None      # 1 or 2 for power play

    # Situational (SUPPLEMENTAL)
    is_b2b: Optional[bool] = None
    days_rest: Optional[int] = None

    # =========================================================================
    # BETTING CONTEXT (from Odds API)
    # =========================================================================
    game_total: Optional[float] = None  # O/U for game
    spread: Optional[float] = None      # Point spread

    def get_season_avg(self, stat_type: str) -> Optional[float]:
        """Get season average for a stat type."""
        # If pre-calculated average is available
        if self.season_avg is not None and stat_type == self.stat_type:
            return float(self.season_avg)

        if not self.season_games or self.season_games == 0:
            return None

        games = float(self.season_games)
        if stat_type == 'points':
            pts = float(self.season_points) if self.season_points else 0
            return pts / games
        elif stat_type == 'goals':
            goals = float(self.season_goals) if self.season_goals else 0
            return goals / games
        elif stat_type == 'assists':
            assists = float(self.season_assists) if self.season_assists else 0
            return assists / games
        elif stat_type == 'shots_on_goal':
            shots = float(self.season_shots) if self.season_shots else 0
            return shots / games
        return None

    def get_recent_avg(self, stat_type: str) -> Optional[float]:
        """Get recent average for a stat type."""
        if self.recent_avg is not None and stat_type == self.stat_type:
            return float(self.recent_avg)
        return float(self.recent_ppg) if self.recent_ppg is not None else None

    @property
    def has_nhl_api_data(self) -> bool:
        """Check if we have primary NHL API data."""
        return self.season_games is not None and self.season_games > 0

    @property
    def has_pipeline_data(self) -> bool:
        """Check if we have supplemental pipeline data."""
        return self.pipeline_score is not None
