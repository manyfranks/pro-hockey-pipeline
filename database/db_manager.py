# nhl_isolated/database/db_manager.py
"""
NHL Database Manager

Handles PostgreSQL database operations for NHL player points predictions.
Mirrors the MLB db_manager pattern but adapted for NHL-specific data.
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, text, Table, Column, MetaData,
    Integer, BigInteger, String, Date, Numeric, Boolean, TIMESTAMP,
    UniqueConstraint, select, ForeignKey
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert, JSONB


class NHLDBManager:
    """Manages connection and data persistence for NHL predictions."""

    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize database connection.

        Args:
            env_path: Path to .env file. Defaults to .env.local in project root.
        """
        if env_path:
            load_dotenv(dotenv_path=env_path)
        else:
            # Try common locations
            for path in ['.env.local', '../.env.local', '../../.env.local']:
                if os.path.exists(path):
                    load_dotenv(dotenv_path=path)
                    break

        self.connection_string = os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise ValueError("DATABASE_URL environment variable not set.")

        print(f"[NHL DB] Connecting to database...")

        # Create engine with SSL and connection pooling
        self.engine = create_engine(
            self.connection_string,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_timeout=30,
            max_overflow=20,
            pool_size=10,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 20,
                "keepalives_idle": 600,
                "keepalives_interval": 30,
                "keepalives_count": 3
            }
        )
        self.Session = sessionmaker(bind=self.engine)

        # Define table schemas
        self.meta = MetaData()
        self._define_tables()

        print("[NHL DB] Connection established.")

    def _define_tables(self):
        """Define all NHL table schemas."""

        # NHL Players table
        self.nhl_players_table = Table('nhl_players', self.meta,
            Column('player_id', Integer, primary_key=True),
            Column('full_name', String(255)),
            Column('team', String(10)),
            Column('position', String(5)),
            Column('jersey_number', Integer, nullable=True),
            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())"))
        )

        # NHL Games table
        self.nhl_games_table = Table('nhl_games', self.meta,
            Column('game_id', Integer, primary_key=True),
            Column('home_team', String(10)),
            Column('away_team', String(10)),
            Column('game_date', Date),
            Column('game_time', TIMESTAMP, nullable=True),
            Column('season', String(10)),
            Column('status', String(20)),  # Scheduled, Final, InProgress, Postponed
            Column('home_score', Integer, nullable=True),
            Column('away_score', Integer, nullable=True),
            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())"))
        )

        # NHL Daily Predictions table (main predictions table)
        self.nhl_daily_predictions_table = Table('nhl_daily_predictions', self.meta,
            Column('prediction_id', Integer, primary_key=True, autoincrement=True),
            Column('player_id', Integer, nullable=False),
            Column('game_id', Integer, nullable=False),
            Column('analysis_date', Date, nullable=False),

            # Player context
            Column('player_name', String(255)),
            Column('team', String(10)),
            Column('position', String(5)),
            Column('opponent', String(10)),
            Column('is_home', Boolean),

            # Final score and ranking
            Column('final_score', Numeric(8, 4)),
            Column('rank', Integer),  # Daily rank (1 = top pick)
            Column('confidence', String(20)),  # very_high, high, medium, low

            # Component scores (0-1 scale)
            Column('recent_form_score', Numeric(8, 4)),
            Column('line_opportunity_score', Numeric(8, 4)),
            Column('goalie_weakness_score', Numeric(8, 4)),
            Column('matchup_score', Numeric(8, 4)),
            Column('situational_score', Numeric(8, 4)),

            # Component details (for transparency/debugging)
            Column('component_details', JSONB),  # Full breakdown of all components

            # Line/PP info
            Column('line_number', Integer),
            Column('pp_unit', Integer),  # 0, 1, or 2
            Column('avg_toi_minutes', Numeric(6, 2)),

            # Recent form details
            Column('recent_ppg', Numeric(6, 3)),
            Column('recent_games', Integer),
            Column('recent_points', Integer),
            Column('recent_goals', Integer),
            Column('recent_assists', Integer),
            Column('point_streak', Integer),

            # Opposing goalie info
            Column('opposing_goalie_id', Integer, nullable=True),
            Column('opposing_goalie_name', String(255), nullable=True),
            Column('opposing_goalie_sv_pct', Numeric(6, 4), nullable=True),
            Column('opposing_goalie_gaa', Numeric(6, 3), nullable=True),
            Column('goalie_confirmed', Boolean),

            # Matchup details
            Column('matchup_method', String(30)),  # nhl_api_conditional, elite_goalie_weighted, etc.

            # Situational factors
            Column('is_b2b', Boolean, default=False),
            Column('is_b2b2b', Boolean, default=False),
            Column('days_rest', Integer, nullable=True),
            Column('opposing_goalie_b2b', Boolean, default=False),

            # Season stats (for context/analysis)
            Column('season_games', Integer, nullable=True),
            Column('season_goals', Integer, nullable=True),
            Column('season_assists', Integer, nullable=True),
            Column('season_points', Integer, nullable=True),
            Column('season_pp_goals', Integer, nullable=True),

            # Settlement (filled in after game)
            Column('actual_points', Integer, nullable=True),  # 0, 1, 2, 3, etc.
            Column('actual_goals', Integer, nullable=True),
            Column('actual_assists', Integer, nullable=True),
            Column('point_outcome', Integer, nullable=True),  # 1: Got point, 0: No point, 2: PPD, 3: DNP

            # Scoring gate flag - only these predictions count toward hit rate
            # Criteria: (line_number <= 3 OR pp_unit >= 1) AND final_score >= 55
            Column('is_scoreable', Boolean, default=False),

            # Timestamps
            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())")),

            UniqueConstraint('player_id', 'game_id', 'analysis_date', name='uq_nhl_daily_prediction')
        )

        # NHL Goalies table (for tracking goalie stats separately)
        self.nhl_goalies_table = Table('nhl_goalies', self.meta,
            Column('goalie_id', Integer, primary_key=True),
            Column('full_name', String(255)),
            Column('team', String(10)),
            Column('season_games', Integer),
            Column('season_starts', Integer),
            Column('save_percentage', Numeric(6, 4)),
            Column('goals_against_average', Numeric(6, 3)),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())"))
        )

        # NHL Line Combinations table (from DailyFaceoff)
        # Tracks line combinations over time for historical analysis and fallback
        self.nhl_line_combinations_table = Table('nhl_line_combinations', self.meta,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('team', String(10), nullable=False),
            Column('captured_date', Date, nullable=False),
            Column('source', String(100)),  # e.g., "DailyFaceoff - Jason Gregor"
            Column('source_updated_at', TIMESTAMP, nullable=True),  # When source last updated

            # Line data as JSONB for flexibility
            Column('forward_lines', JSONB),    # {1: {lw, c, rw}, 2: {...}, ...}
            Column('defense_pairs', JSONB),    # {1: {ld, rd}, 2: {...}, 3: {...}}
            Column('power_play', JSONB),       # {1: {players: [...]}, 2: {...}}
            Column('penalty_kill', JSONB),     # {1: {players: [...]}, 2: {...}}
            Column('goalies', JSONB),          # [{name, jersey_number, is_starter}, ...]
            Column('players_by_line', JSONB),  # {player_name: {line, pp_unit, position}}

            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),

            UniqueConstraint('team', 'captured_date', name='uq_nhl_line_combo_team_date')
        )

        # NHL Daily Insights table (caches LLM narratives and full reports)
        # Hot streaks, parlays, etc. are computed on-the-fly from nhl_daily_predictions
        # Only the expensive LLM narrative is cached here
        self.nhl_daily_insights_table = Table('nhl_daily_insights', self.meta,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('analysis_date', Date, nullable=False, unique=True),

            # LLM-generated content (expensive to regenerate)
            Column('llm_narrative', String, nullable=True),  # Full LLM analysis text
            Column('llm_model', String(100), nullable=True),  # Model used (e.g., google/gemini-2.0-flash-001)

            # Full insights report as JSONB (hot streaks, parlays, etc.)
            Column('full_report', JSONB, nullable=True),

            # Metadata
            Column('total_predictions', Integer),
            Column('games_count', Integer),
            Column('generated_at', TIMESTAMP),
            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())"))
        )

    def create_tables(self):
        """Create all tables if they don't exist."""
        self.meta.create_all(self.engine)
        print("[NHL DB] Tables created/verified.")

    # -------------------------------------------------------------------------
    # Player Operations
    # -------------------------------------------------------------------------

    def upsert_players(self, players: List[Dict[str, Any]]):
        """
        Upsert player records.

        Args:
            players: List of player dictionaries with player_id, full_name, team, position
        """
        if not players:
            return

        with self.Session() as session:
            for player in players:
                stmt = insert(self.nhl_players_table).values(
                    player_id=player['player_id'],
                    full_name=player.get('player_name') or player.get('full_name'),
                    team=player.get('team'),
                    position=player.get('position'),
                    jersey_number=player.get('jersey_number')
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['player_id'],
                    set_={
                        'full_name': stmt.excluded.full_name,
                        'team': stmt.excluded.team,
                        'position': stmt.excluded.position,
                        'jersey_number': stmt.excluded.jersey_number,
                        'updated_at': text("timezone('utc', now())")
                    }
                )
                session.execute(stmt)
            session.commit()

        print(f"[NHL DB] Upserted {len(players)} player records.")

    # -------------------------------------------------------------------------
    # Game Operations
    # -------------------------------------------------------------------------

    def upsert_games(self, games: List[Dict[str, Any]]):
        """
        Upsert game records.

        Args:
            games: List of game dictionaries
        """
        if not games:
            return

        with self.Session() as session:
            for game in games:
                stmt = insert(self.nhl_games_table).values(
                    game_id=game['game_id'],
                    home_team=game.get('home_team') or game.get('HomeTeam'),
                    away_team=game.get('away_team') or game.get('AwayTeam'),
                    game_date=game.get('game_date'),
                    game_time=game.get('game_time') or game.get('DateTime'),
                    season=game.get('season'),
                    status=game.get('status') or game.get('Status', 'Scheduled')
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['game_id'],
                    set_={
                        'home_team': stmt.excluded.home_team,
                        'away_team': stmt.excluded.away_team,
                        'game_date': stmt.excluded.game_date,
                        'game_time': stmt.excluded.game_time,
                        'status': stmt.excluded.status,
                        'home_score': stmt.excluded.home_score,
                        'away_score': stmt.excluded.away_score,
                        'updated_at': text("timezone('utc', now())")
                    }
                )
                session.execute(stmt)
            session.commit()

        print(f"[NHL DB] Upserted {len(games)} game records.")

    # -------------------------------------------------------------------------
    # Prediction Operations
    # -------------------------------------------------------------------------

    def upsert_predictions(self, predictions: List[Dict[str, Any]], analysis_date: date):
        """
        Upsert daily predictions.

        Args:
            predictions: List of enriched player dictionaries with scores
            analysis_date: Date of the analysis
        """
        if not predictions:
            return

        with self.Session() as session:
            for rank, player in enumerate(predictions, 1):
                # Extract component details
                component_details = {
                    'component_scores': player.get('component_scores', {}),
                    'form_details': player.get('form_details', {}),
                    'opportunity_details': player.get('opportunity_details', {}),
                    'goalie_weakness_details': player.get('goalie_weakness_details', {}),
                    'matchup_details': player.get('matchup_details', {}),
                    'situational_details': player.get('situational_details', {}),
                }

                # Get matchup method
                matchup_details = player.get('matchup_details', {})
                matchup_method = matchup_details.get('method', 'unknown')

                # Get situational details
                situational = player.get('situational_details', {})

                # Extract component scores (fallback to component_scores dict if top-level is None)
                component_scores = player.get('component_scores', {})
                matchup_score = player.get('matchup_score') or component_scores.get('matchup', {}).get('raw')
                situational_score = player.get('situational_score') or component_scores.get('situational', {}).get('raw')
                days_rest = situational.get('days_rest')

                # Compute is_scoreable: Core players (Top 3 lines OR PP) with score >= 55
                line_num = player.get('line_number', 4)
                pp_unit = player.get('pp_unit', 0)
                final_score = player.get('final_score', 0) or 0
                is_core = (line_num <= 3) or (pp_unit >= 1)
                is_scoreable = is_core and (final_score >= 55)

                stmt = insert(self.nhl_daily_predictions_table).values(
                    player_id=player['player_id'],
                    game_id=player['game_id'],
                    analysis_date=analysis_date,

                    # Player context
                    player_name=player.get('player_name'),
                    team=player.get('team'),
                    position=player.get('position'),
                    opponent=player.get('opponent'),
                    is_home=player.get('is_home', False),

                    # Scores
                    final_score=player.get('final_score'),
                    rank=rank,
                    confidence=player.get('confidence'),

                    # Component scores
                    recent_form_score=player.get('recent_form_score'),
                    line_opportunity_score=player.get('line_opportunity_score'),
                    goalie_weakness_score=player.get('goalie_weakness_score'),
                    matchup_score=matchup_score,
                    situational_score=situational_score,

                    # Component details JSON
                    component_details=json.dumps(component_details),

                    # Line/PP info
                    line_number=player.get('line_number'),
                    pp_unit=player.get('pp_unit'),
                    avg_toi_minutes=player.get('avg_toi_minutes'),

                    # Recent form
                    recent_ppg=player.get('recent_ppg'),
                    recent_games=player.get('recent_games'),
                    recent_points=player.get('recent_points'),
                    recent_goals=player.get('recent_goals'),
                    recent_assists=player.get('recent_assists'),
                    point_streak=player.get('point_streak'),

                    # Opposing goalie
                    opposing_goalie_id=player.get('opposing_goalie_id'),
                    opposing_goalie_name=player.get('opposing_goalie_name'),
                    opposing_goalie_sv_pct=player.get('opposing_goalie_sv_pct'),
                    opposing_goalie_gaa=player.get('opposing_goalie_gaa'),
                    goalie_confirmed=player.get('goalie_confirmed', False),

                    # Matchup
                    matchup_method=matchup_method,

                    # Situational
                    is_b2b=situational.get('is_b2b', False),
                    is_b2b2b=situational.get('is_b2b2b', False),
                    days_rest=days_rest,
                    opposing_goalie_b2b=situational.get('opposing_goalie_b2b', False),

                    # Season stats
                    season_games=player.get('season_games'),
                    season_goals=player.get('season_goals'),
                    season_assists=player.get('season_assists'),
                    season_points=player.get('season_points'),
                    season_pp_goals=player.get('season_pp_goals'),

                    # Scoring gate
                    is_scoreable=is_scoreable,
                )

                stmt = stmt.on_conflict_do_update(
                    constraint='uq_nhl_daily_prediction',
                    set_={
                        'player_name': stmt.excluded.player_name,
                        'team': stmt.excluded.team,
                        'position': stmt.excluded.position,
                        'opponent': stmt.excluded.opponent,
                        'is_home': stmt.excluded.is_home,
                        'final_score': stmt.excluded.final_score,
                        'rank': stmt.excluded.rank,
                        'confidence': stmt.excluded.confidence,
                        'recent_form_score': stmt.excluded.recent_form_score,
                        'line_opportunity_score': stmt.excluded.line_opportunity_score,
                        'goalie_weakness_score': stmt.excluded.goalie_weakness_score,
                        'matchup_score': stmt.excluded.matchup_score,
                        'situational_score': stmt.excluded.situational_score,
                        'component_details': stmt.excluded.component_details,
                        'line_number': stmt.excluded.line_number,
                        'pp_unit': stmt.excluded.pp_unit,
                        'avg_toi_minutes': stmt.excluded.avg_toi_minutes,
                        'recent_ppg': stmt.excluded.recent_ppg,
                        'recent_games': stmt.excluded.recent_games,
                        'recent_points': stmt.excluded.recent_points,
                        'recent_goals': stmt.excluded.recent_goals,
                        'recent_assists': stmt.excluded.recent_assists,
                        'point_streak': stmt.excluded.point_streak,
                        'opposing_goalie_id': stmt.excluded.opposing_goalie_id,
                        'opposing_goalie_name': stmt.excluded.opposing_goalie_name,
                        'opposing_goalie_sv_pct': stmt.excluded.opposing_goalie_sv_pct,
                        'opposing_goalie_gaa': stmt.excluded.opposing_goalie_gaa,
                        'goalie_confirmed': stmt.excluded.goalie_confirmed,
                        'matchup_method': stmt.excluded.matchup_method,
                        'is_b2b': stmt.excluded.is_b2b,
                        'is_b2b2b': stmt.excluded.is_b2b2b,
                        'days_rest': stmt.excluded.days_rest,
                        'opposing_goalie_b2b': stmt.excluded.opposing_goalie_b2b,
                        'season_games': stmt.excluded.season_games,
                        'season_goals': stmt.excluded.season_goals,
                        'season_assists': stmt.excluded.season_assists,
                        'season_points': stmt.excluded.season_points,
                        'season_pp_goals': stmt.excluded.season_pp_goals,
                        'is_scoreable': stmt.excluded.is_scoreable,
                        'updated_at': text("timezone('utc', now())")
                    }
                )
                session.execute(stmt)
            session.commit()

        print(f"[NHL DB] Upserted {len(predictions)} prediction records for {analysis_date}.")

    # -------------------------------------------------------------------------
    # Line Combinations Operations
    # -------------------------------------------------------------------------

    def upsert_line_combinations(self, line_data: Dict[str, Dict], captured_date: date):
        """
        Upsert line combinations for all teams.

        Args:
            line_data: Dict mapping team abbreviation to line combination data
            captured_date: Date when line data was captured
        """
        if not line_data:
            return

        with self.Session() as session:
            for team_abbrev, team_data in line_data.items():
                # Parse source updated timestamp if available
                source_updated = None
                if team_data.get('updated_at'):
                    try:
                        source_updated = datetime.fromisoformat(
                            team_data['updated_at'].replace('Z', '+00:00')
                        )
                    except (ValueError, TypeError):
                        pass

                stmt = insert(self.nhl_line_combinations_table).values(
                    team=team_abbrev,
                    captured_date=captured_date,
                    source=team_data.get('source'),
                    source_updated_at=source_updated,
                    forward_lines=json.dumps(team_data.get('forward_lines', {})),
                    defense_pairs=json.dumps(team_data.get('defense_pairs', {})),
                    power_play=json.dumps(team_data.get('power_play', {})),
                    penalty_kill=json.dumps(team_data.get('penalty_kill', {})),
                    goalies=json.dumps(team_data.get('goalies', [])),
                    players_by_line=json.dumps(team_data.get('players_by_line', {})),
                )

                stmt = stmt.on_conflict_do_update(
                    constraint='uq_nhl_line_combo_team_date',
                    set_={
                        'source': stmt.excluded.source,
                        'source_updated_at': stmt.excluded.source_updated_at,
                        'forward_lines': stmt.excluded.forward_lines,
                        'defense_pairs': stmt.excluded.defense_pairs,
                        'power_play': stmt.excluded.power_play,
                        'penalty_kill': stmt.excluded.penalty_kill,
                        'goalies': stmt.excluded.goalies,
                        'players_by_line': stmt.excluded.players_by_line,
                    }
                )
                session.execute(stmt)
            session.commit()

        print(f"[NHL DB] Upserted line combinations for {len(line_data)} teams on {captured_date}.")

    def get_line_combinations(self, team: str, target_date: date = None) -> Optional[Dict]:
        """
        Get line combinations for a team.

        Args:
            team: Team abbreviation
            target_date: Date to get lines for (default: most recent)

        Returns:
            Line combination data or None
        """
        with self.Session() as session:
            if target_date:
                stmt = select(self.nhl_line_combinations_table).where(
                    (self.nhl_line_combinations_table.c.team == team) &
                    (self.nhl_line_combinations_table.c.captured_date == target_date)
                )
            else:
                # Get most recent
                stmt = select(self.nhl_line_combinations_table).where(
                    self.nhl_line_combinations_table.c.team == team
                ).order_by(
                    self.nhl_line_combinations_table.c.captured_date.desc()
                ).limit(1)

            result = session.execute(stmt).fetchone()

            if not result:
                return None

            columns = [col.name for col in self.nhl_line_combinations_table.columns]
            data = dict(zip(columns, result))

            # Parse JSONB fields
            for field in ['forward_lines', 'defense_pairs', 'power_play',
                         'penalty_kill', 'goalies', 'players_by_line']:
                if data.get(field) and isinstance(data[field], str):
                    data[field] = json.loads(data[field])

            return data

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    def get_predictions_by_date(self, analysis_date: date, top_n: int = None) -> List[Dict[str, Any]]:
        """
        Retrieve predictions for a specific date.

        Args:
            analysis_date: Date to fetch predictions for
            top_n: Limit to top N predictions (by rank)

        Returns:
            List of prediction dictionaries
        """
        with self.Session() as session:
            stmt = select(self.nhl_daily_predictions_table).where(
                self.nhl_daily_predictions_table.c.analysis_date == analysis_date
            ).order_by(self.nhl_daily_predictions_table.c.rank)

            if top_n:
                stmt = stmt.limit(top_n)

            result = session.execute(stmt)
            rows = result.fetchall()

            if not rows:
                return []

            columns = [col.name for col in self.nhl_daily_predictions_table.columns]
            return [dict(zip(columns, row)) for row in rows]

    def get_unsettled_predictions(self, analysis_date: date) -> List[Dict[str, Any]]:
        """
        Get predictions that haven't been settled yet.

        Args:
            analysis_date: Date to fetch unsettled predictions for

        Returns:
            List of unsettled prediction dictionaries
        """
        with self.Session() as session:
            stmt = select(
                self.nhl_daily_predictions_table.c.prediction_id,
                self.nhl_daily_predictions_table.c.player_id,
                self.nhl_daily_predictions_table.c.game_id,
                self.nhl_daily_predictions_table.c.analysis_date,
                self.nhl_daily_predictions_table.c.player_name,
                self.nhl_daily_predictions_table.c.team,
                self.nhl_daily_predictions_table.c.rank,
                self.nhl_daily_predictions_table.c.final_score
            ).where(
                (self.nhl_daily_predictions_table.c.analysis_date == analysis_date) &
                (self.nhl_daily_predictions_table.c.point_outcome.is_(None))
            )

            result = session.execute(stmt)
            rows = result.fetchall()

            if not rows:
                return []

            columns = ['prediction_id', 'player_id', 'game_id', 'analysis_date',
                      'player_name', 'team', 'rank', 'final_score']
            return [dict(zip(columns, row)) for row in rows]

    def update_settlement(self, settlements: List[Dict[str, Any]]):
        """
        Update predictions with actual game results.

        Args:
            settlements: List of dicts with player_id, game_id, analysis_date,
                        actual_points, actual_goals, actual_assists, point_outcome
        """
        if not settlements:
            return

        with self.Session() as session:
            for s in settlements:
                stmt = text("""
                    UPDATE nhl_daily_predictions
                    SET actual_points = :actual_points,
                        actual_goals = :actual_goals,
                        actual_assists = :actual_assists,
                        point_outcome = :point_outcome,
                        updated_at = timezone('utc', now())
                    WHERE player_id = :player_id
                    AND game_id = :game_id
                    AND analysis_date = :analysis_date
                """)

                session.execute(stmt, {
                    'actual_points': s.get('actual_points'),
                    'actual_goals': s.get('actual_goals'),
                    'actual_assists': s.get('actual_assists'),
                    'point_outcome': s.get('point_outcome'),
                    'player_id': s['player_id'],
                    'game_id': s['game_id'],
                    'analysis_date': s['analysis_date']
                })
            session.commit()

        print(f"[NHL DB] Updated settlement for {len(settlements)} predictions.")

    def get_hit_rate_summary(
        self,
        start_date: date = None,
        end_date: date = None,
        scoreable_only: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate hit rate statistics for predictions.

        Args:
            start_date: Start of date range (optional)
            end_date: End of date range (optional)
            scoreable_only: If True (default), only count predictions where is_scoreable=True.
                           This filters to Core players (Top 3 lines OR PP) with score >= 55.
                           Set to False for full analytics across all predictions.

        Returns:
            Dictionary with hit rate statistics by tier
        """
        with self.Session() as session:
            # Build filters
            base_filter = ""
            params = {}

            # Scoreable filter (default: only count gated predictions)
            if scoreable_only:
                base_filter += " AND is_scoreable = TRUE"

            if start_date:
                base_filter += " AND analysis_date >= :start_date"
                params['start_date'] = start_date
            if end_date:
                base_filter += " AND analysis_date <= :end_date"
                params['end_date'] = end_date

            # Overall hit rate
            stmt = text(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END) as hits,
                    SUM(CASE WHEN point_outcome = 0 THEN 1 ELSE 0 END) as misses,
                    SUM(CASE WHEN point_outcome IN (2, 3) THEN 1 ELSE 0 END) as excluded
                FROM nhl_daily_predictions
                WHERE point_outcome IS NOT NULL {base_filter}
            """)

            result = session.execute(stmt, params).fetchone()

            # By confidence tier
            tier_stmt = text(f"""
                SELECT
                    confidence,
                    COUNT(*) as total,
                    SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END) as hits,
                    ROUND(SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END)::numeric /
                          NULLIF(SUM(CASE WHEN point_outcome IN (0, 1) THEN 1 ELSE 0 END), 0) * 100, 1) as hit_rate
                FROM nhl_daily_predictions
                WHERE point_outcome IS NOT NULL {base_filter}
                GROUP BY confidence
                ORDER BY
                    CASE confidence
                        WHEN 'very_high' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                    END
            """)

            tier_results = session.execute(tier_stmt, params).fetchall()

            # By rank bucket (Top 5, Top 10, Top 25)
            rank_stmt = text(f"""
                WITH ranked AS (
                    SELECT
                        CASE
                            WHEN rank <= 5 THEN 'Top 5'
                            WHEN rank <= 10 THEN 'Top 10'
                            WHEN rank <= 25 THEN 'Top 25'
                            ELSE 'Other'
                        END as rank_bucket,
                        CASE
                            WHEN rank <= 5 THEN 1
                            WHEN rank <= 10 THEN 2
                            WHEN rank <= 25 THEN 3
                            ELSE 4
                        END as sort_order,
                        point_outcome
                    FROM nhl_daily_predictions
                    WHERE point_outcome IS NOT NULL {base_filter}
                )
                SELECT
                    rank_bucket,
                    COUNT(*) as total,
                    SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END) as hits,
                    ROUND(SUM(CASE WHEN point_outcome = 1 THEN 1 ELSE 0 END)::numeric /
                          NULLIF(SUM(CASE WHEN point_outcome IN (0, 1) THEN 1 ELSE 0 END), 0) * 100, 1) as hit_rate
                FROM ranked
                GROUP BY rank_bucket, sort_order
                ORDER BY sort_order
            """)

            rank_results = session.execute(rank_stmt, params).fetchall()

            total = result[0] or 0
            hits = result[1] or 0
            misses = result[2] or 0
            excluded = result[3] or 0
            valid = hits + misses

            return {
                'total_predictions': total,
                'settled': valid,
                'excluded': excluded,
                'hits': hits,
                'misses': misses,
                'overall_hit_rate': round(hits / valid * 100, 1) if valid > 0 else None,
                'scoreable_only': scoreable_only,
                'by_confidence': [
                    {'tier': r[0], 'total': r[1], 'hits': r[2], 'hit_rate': float(r[3]) if r[3] else None}
                    for r in tier_results
                ],
                'by_rank': [
                    {'bucket': r[0], 'total': r[1], 'hits': r[2], 'hit_rate': float(r[3]) if r[3] else None}
                    for r in rank_results
                ]
            }

    def get_predictions_for_date(
        self,
        analysis_date: date,
        top_n: int = None,
        scoreable_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all predictions for a specific date (for insights generation).

        Args:
            analysis_date: Date to fetch predictions for
            top_n: Optional limit to top N predictions by rank
            scoreable_only: If True, only return predictions where is_scoreable=True

        Returns:
            List of prediction dictionaries with full data for insights
        """
        with self.Session() as session:
            limit_clause = f"LIMIT {top_n}" if top_n else ""
            scoreable_filter = "AND is_scoreable = TRUE" if scoreable_only else ""

            stmt = text(f"""
                SELECT
                    player_id,
                    player_name,
                    team,
                    position,
                    game_id,
                    analysis_date,
                    opponent,
                    is_home,
                    line_number,
                    pp_unit,
                    season_games,
                    season_goals,
                    season_assists,
                    season_points,
                    season_pp_goals,
                    avg_toi_minutes,
                    recent_ppg,
                    point_streak,
                    opposing_goalie_name,
                    opposing_goalie_sv_pct,
                    opposing_goalie_gaa,
                    final_score,
                    confidence,
                    rank,
                    matchup_score,
                    situational_score,
                    point_outcome,
                    actual_points,
                    actual_goals,
                    actual_assists,
                    is_scoreable
                FROM nhl_daily_predictions
                WHERE analysis_date = :analysis_date {scoreable_filter}
                ORDER BY rank ASC NULLS LAST, final_score DESC
                {limit_clause}
            """)

            result = session.execute(stmt, {'analysis_date': analysis_date})
            rows = result.fetchall()

            if not rows:
                return []

            columns = [
                'player_id', 'player_name', 'team', 'position', 'game_id',
                'analysis_date', 'opponent', 'is_home', 'line_number', 'pp_unit',
                'season_games', 'season_goals', 'season_assists', 'season_points',
                'season_pp_goals', 'avg_toi_minutes', 'recent_ppg', 'point_streak',
                'opposing_goalie_name', 'opposing_goalie_sv_pct', 'opposing_goalie_gaa',
                'final_score', 'confidence', 'rank', 'matchup_score', 'situational_score',
                'point_outcome', 'actual_points', 'actual_goals', 'actual_assists',
                'is_scoreable'
            ]

            predictions = []
            for row in rows:
                pred = dict(zip(columns, row))
                # Convert date to string for consistency with JSON format
                if pred.get('analysis_date'):
                    pred['analysis_date'] = str(pred['analysis_date'])
                predictions.append(pred)

            return predictions

    def get_recent_settled_predictions(
        self,
        lookback_days: int = 5,
        top_n_per_day: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recently settled predictions for performance analysis.

        Args:
            lookback_days: Number of days to look back
            top_n_per_day: Limit to top N predictions per day

        Returns:
            List of settled predictions with outcomes
        """
        with self.Session() as session:
            stmt = text("""
                WITH ranked_by_day AS (
                    SELECT
                        player_id,
                        player_name,
                        team,
                        analysis_date,
                        final_score,
                        confidence,
                        rank,
                        point_outcome,
                        actual_points,
                        ROW_NUMBER() OVER (PARTITION BY analysis_date ORDER BY rank ASC) as day_rank
                    FROM nhl_daily_predictions
                    WHERE point_outcome IS NOT NULL
                    AND analysis_date >= CURRENT_DATE - :lookback_days
                    AND analysis_date < CURRENT_DATE
                )
                SELECT *
                FROM ranked_by_day
                WHERE day_rank <= :top_n
                ORDER BY analysis_date DESC, rank ASC
            """)

            result = session.execute(stmt, {
                'lookback_days': lookback_days,
                'top_n': top_n_per_day
            })
            rows = result.fetchall()

            if not rows:
                return []

            columns = [
                'player_id', 'player_name', 'team', 'analysis_date',
                'final_score', 'confidence', 'rank', 'point_outcome',
                'actual_points', 'day_rank'
            ]

            return [dict(zip(columns, row)) for row in rows]

    # -------------------------------------------------------------------------
    # Daily Insights Operations (LLM narrative caching)
    # -------------------------------------------------------------------------

    def upsert_daily_insights(
        self,
        analysis_date: date,
        llm_narrative: Optional[str] = None,
        llm_model: Optional[str] = None,
        full_report: Optional[Dict] = None,
        total_predictions: int = 0,
        games_count: int = 0
    ):
        """
        Upsert daily insights (primarily for caching LLM narratives).

        Args:
            analysis_date: Date of the analysis
            llm_narrative: LLM-generated narrative text
            llm_model: Model used for generation
            full_report: Full InsightsReport as dict
            total_predictions: Number of predictions analyzed
            games_count: Number of games for the day
        """
        with self.Session() as session:
            stmt = insert(self.nhl_daily_insights_table).values(
                analysis_date=analysis_date,
                llm_narrative=llm_narrative,
                llm_model=llm_model,
                full_report=json.dumps(full_report) if full_report else None,
                total_predictions=total_predictions,
                games_count=games_count,
                generated_at=datetime.utcnow()
            )

            stmt = stmt.on_conflict_do_update(
                index_elements=['analysis_date'],
                set_={
                    'llm_narrative': stmt.excluded.llm_narrative,
                    'llm_model': stmt.excluded.llm_model,
                    'full_report': stmt.excluded.full_report,
                    'total_predictions': stmt.excluded.total_predictions,
                    'games_count': stmt.excluded.games_count,
                    'generated_at': stmt.excluded.generated_at,
                    'updated_at': text("timezone('utc', now())")
                }
            )
            session.execute(stmt)
            session.commit()

        print(f"[NHL DB] Upserted daily insights for {analysis_date}.")

    def get_daily_insights(self, analysis_date: date) -> Optional[Dict[str, Any]]:
        """
        Get cached daily insights for a date.

        Args:
            analysis_date: Date to fetch insights for

        Returns:
            Dict with llm_narrative, full_report, etc. or None if not found
        """
        with self.Session() as session:
            stmt = select(self.nhl_daily_insights_table).where(
                self.nhl_daily_insights_table.c.analysis_date == analysis_date
            )

            result = session.execute(stmt).fetchone()

            if not result:
                return None

            columns = [col.name for col in self.nhl_daily_insights_table.columns]
            data = dict(zip(columns, result))

            # Parse JSONB full_report if present
            if data.get('full_report') and isinstance(data['full_report'], str):
                data['full_report'] = json.loads(data['full_report'])

            return data

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.Session() as session:
                session.execute(text("SELECT 1"))
            print("[NHL DB] Connection test successful.")
            return True
        except Exception as e:
            print(f"[NHL DB] Connection test failed: {e}")
            return False


# Convenience function for quick access
def get_db_manager() -> NHLDBManager:
    """Get a database manager instance."""
    return NHLDBManager()


if __name__ == '__main__':
    # Test the database connection
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    db = NHLDBManager()

    if db.test_connection():
        print("\nCreating tables...")
        db.create_tables()
        print("Done!")
    else:
        print("Failed to connect to database.")
