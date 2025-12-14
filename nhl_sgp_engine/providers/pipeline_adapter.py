"""
Pipeline Adapter for NHL SGP Engine

Bridges the SGP engine to the existing NHL points prediction pipeline.
Enriches prop context with pipeline predictions and player data.
"""
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load env for database connection
for env_path in ['.env', '.env.local', '../.env', '../.env.local']:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..signals.base import PropContext


class PipelineAdapter:
    """
    Adapts existing NHL pipeline data for SGP edge detection.

    Provides:
    - Player context from nhl_daily_predictions
    - Season stats and recent form
    - Line/PP deployment info
    - Goalie matchup data
    - Situational factors (B2B, rest)
    """

    def __init__(self):
        """Initialize connection to NHL pipeline database."""
        connection_string = os.getenv("DATABASE_URL")
        if not connection_string:
            raise ValueError("DATABASE_URL not set")

        self.engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"}
        )
        self.Session = sessionmaker(bind=self.engine)

        # Cache for player lookups
        self._player_cache = {}
        self._prediction_cache = {}

    def get_prediction_context(
        self,
        player_name: str,
        game_date: date,
    ) -> Optional[Dict[str, Any]]:
        """
        Get pipeline prediction context for a player on a specific date.

        Args:
            player_name: Player's full name
            game_date: Date of the game

        Returns:
            Dict with prediction context or None if not found
        """
        cache_key = f"{player_name}_{game_date}"
        if cache_key in self._prediction_cache:
            return self._prediction_cache[cache_key]

        with self.Session() as session:
            # Query predictions table
            result = session.execute(text("""
                SELECT
                    p.player_id,
                    p.player_name,
                    p.team,
                    p.position,
                    p.opponent,
                    p.is_home,
                    p.game_id,

                    -- Scores
                    p.final_score,
                    p.rank,
                    p.confidence,
                    p.is_scoreable,

                    -- Component scores
                    p.recent_form_score,
                    p.line_opportunity_score,
                    p.goalie_weakness_score,
                    p.matchup_score,
                    p.situational_score,

                    -- Line/PP info
                    p.line_number,
                    p.pp_unit,
                    p.avg_toi_minutes,

                    -- Recent form
                    p.recent_ppg,
                    p.recent_games,
                    p.recent_points,
                    p.recent_goals,
                    p.recent_assists,
                    p.point_streak,

                    -- Goalie matchup
                    p.opposing_goalie_id,
                    p.opposing_goalie_name,
                    p.opposing_goalie_sv_pct,
                    p.opposing_goalie_gaa,
                    p.goalie_confirmed,

                    -- Situational
                    p.is_b2b,

                    -- Season stats
                    p.season_games,
                    p.season_goals,
                    p.season_assists,
                    p.season_points,

                    -- Settlement (if available)
                    p.point_outcome,
                    p.actual_points,
                    p.actual_goals,
                    p.actual_assists

                FROM nhl_daily_predictions p
                WHERE p.player_name ILIKE :player_name
                  AND p.analysis_date = :game_date
                ORDER BY p.final_score DESC
                LIMIT 1
            """), {
                'player_name': f"%{player_name}%",
                'game_date': game_date
            })

            row = result.fetchone()
            if not row:
                self._prediction_cache[cache_key] = None
                return None

            context = dict(row._mapping)
            self._prediction_cache[cache_key] = context
            return context

    def get_predictions_for_date(
        self,
        game_date: date,
        scoreable_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all pipeline predictions for a date.

        Args:
            game_date: Date to fetch predictions for
            scoreable_only: If True, only return scoreable predictions

        Returns:
            List of prediction dictionaries
        """
        with self.Session() as session:
            query = """
                SELECT
                    player_id,
                    player_name,
                    team,
                    position,
                    opponent,
                    is_home,
                    game_id,
                    final_score,
                    rank,
                    confidence,
                    is_scoreable,
                    line_number,
                    pp_unit,
                    avg_toi_minutes,
                    recent_ppg,
                    recent_games,
                    point_streak,
                    opposing_goalie_name,
                    opposing_goalie_sv_pct,
                    opposing_goalie_gaa,
                    is_b2b,
                    season_games,
                    season_goals,
                    season_assists,
                    season_points,
                    point_outcome,
                    actual_points,
                    actual_goals,
                    actual_assists
                FROM nhl_daily_predictions
                WHERE analysis_date = :game_date
            """

            if scoreable_only:
                query += " AND is_scoreable = true"

            query += " ORDER BY rank ASC"

            result = session.execute(text(query), {'game_date': game_date})
            return [dict(row._mapping) for row in result]

    def enrich_prop_context(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        game_date: date,
        event_id: str = "",
        opponent: str = "",
        game_total: float = None,
        spread: float = None,
    ) -> PropContext:
        """
        Build a fully enriched PropContext for edge calculation.

        Args:
            player_name: Player's full name
            stat_type: 'points', 'goals', 'assists', etc.
            line: Prop line value
            game_date: Date of the game
            event_id: Odds API event ID
            opponent: Opponent team (if known)
            game_total: Game O/U total (if available)
            spread: Point spread (if available)

        Returns:
            PropContext with all available pipeline data
        """
        # Get pipeline context
        pipeline = self.get_prediction_context(player_name, game_date)

        if pipeline:
            return PropContext(
                # Basic info
                player_id=pipeline.get('player_id', 0),
                player_name=player_name,
                team=pipeline.get('team', ''),
                position=pipeline.get('position', ''),
                stat_type=stat_type,
                line=line,

                # Game context
                game_id=pipeline.get('game_id', event_id),
                game_date=str(game_date),
                opponent=pipeline.get('opponent', opponent),
                is_home=pipeline.get('is_home', False),

                # Pipeline supplemental
                pipeline_score=pipeline.get('final_score'),
                pipeline_confidence=pipeline.get('confidence'),
                pipeline_rank=pipeline.get('rank'),

                # Recent form
                recent_ppg=pipeline.get('recent_ppg'),
                recent_games=pipeline.get('recent_games'),
                point_streak=pipeline.get('point_streak'),

                # Deployment
                line_number=pipeline.get('line_number'),
                pp_unit=pipeline.get('pp_unit'),
                avg_toi_minutes=float(pipeline.get('avg_toi_minutes')) if pipeline.get('avg_toi_minutes') else None,

                # Goalie matchup
                opposing_goalie_name=pipeline.get('opposing_goalie_name'),
                opposing_goalie_sv_pct=float(pipeline.get('opposing_goalie_sv_pct')) if pipeline.get('opposing_goalie_sv_pct') else None,
                opposing_goalie_gaa=float(pipeline.get('opposing_goalie_gaa')) if pipeline.get('opposing_goalie_gaa') else None,

                # Situational
                is_b2b=pipeline.get('is_b2b'),
                days_rest=None,  # Not directly stored

                # Season stats
                season_games=pipeline.get('season_games'),
                season_points=float(pipeline.get('season_points')) if pipeline.get('season_points') else None,
                season_goals=float(pipeline.get('season_goals')) if pipeline.get('season_goals') else None,
                season_assists=float(pipeline.get('season_assists')) if pipeline.get('season_assists') else None,

                # Betting context
                game_total=game_total,
                spread=spread,
            )
        else:
            # Return minimal context if no pipeline data
            return PropContext(
                player_id=0,
                player_name=player_name,
                team='',
                position='',
                stat_type=stat_type,
                line=line,
                game_id=event_id,
                game_date=str(game_date),
                opponent=opponent,
                is_home=False,
                game_total=game_total,
                spread=spread,
            )

    def get_actual_outcome(
        self,
        player_name: str,
        stat_type: str,
        game_date: date,
    ) -> Optional[float]:
        """
        Get actual stat value for a player on a specific date.

        Args:
            player_name: Player's full name
            stat_type: 'points', 'goals', 'assists'
            game_date: Date of the game

        Returns:
            Actual value or None if not settled
        """
        pipeline = self.get_prediction_context(player_name, game_date)

        if not pipeline or pipeline.get('point_outcome') is None:
            return None

        if stat_type == 'points':
            return pipeline.get('actual_points')
        elif stat_type == 'goals':
            return pipeline.get('actual_goals')
        elif stat_type == 'assists':
            return pipeline.get('actual_assists')

        return None

    def get_date_range_with_settlements(
        self,
        min_days: int = 10,
    ) -> tuple:
        """
        Get date range that has settled predictions.

        Args:
            min_days: Minimum number of days to include

        Returns:
            Tuple of (start_date, end_date)
        """
        with self.Session() as session:
            result = session.execute(text("""
                SELECT analysis_date, COUNT(*) as count
                FROM nhl_daily_predictions
                WHERE point_outcome IS NOT NULL
                GROUP BY analysis_date
                ORDER BY analysis_date DESC
            """))

            dates = [row.analysis_date for row in result]

            if len(dates) < min_days:
                return None, None

            # Return range excluding most recent (might be incomplete)
            return dates[-1], dates[1]

    def clear_cache(self):
        """Clear internal caches."""
        self._player_cache.clear()
        self._prediction_cache.clear()
