"""
NHL SGP Database Manager

Handles PostgreSQL operations for NHL SGP parlays, legs, and settlements.
Schema mirrors NFL/NCAAF SGP tables for consistency.

Tables:
    - nhl_sgp_parlays: Parent parlay records
    - nhl_sgp_legs: Individual prop legs within parlays
    - nhl_sgp_settlements: Settlement records for parlays
    - nhl_sgp_historical_odds: Backtesting cache (not used in production)

NOTE: nhl_sgp_predictions table is DEPRECATED. Use nhl_sgp_parlays + nhl_sgp_legs instead.
"""
import os
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, text, Table, Column, MetaData,
    Integer, String, Date, Numeric, Boolean, TIMESTAMP, Text,
    UniqueConstraint, ForeignKey, Index
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert, JSONB, UUID


class NHLSGPDBManager:
    """
    Manages NHL SGP tables (aligned with NFL/NCAAF architecture):
    - nhl_sgp_parlays: Parent parlay records with thesis, combined odds
    - nhl_sgp_legs: Individual prop legs within parlays
    - nhl_sgp_settlements: Settlement records with profit tracking
    - nhl_sgp_historical_odds: Historical odds cache (for backtesting)

    DEPRECATED: nhl_sgp_predictions - single prop predictions (use parlays/legs instead)
    """

    def __init__(self, env_path: Optional[str] = None):
        """Initialize database connection."""
        if env_path:
            load_dotenv(dotenv_path=env_path)
        else:
            for path in ['.env.local', '.env', '../.env.local', '../.env']:
                if os.path.exists(path):
                    load_dotenv(dotenv_path=path)
                    break

        self.connection_string = os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise ValueError("DATABASE_URL environment variable not set.")

        print("[NHL SGP DB] Connecting to database...")

        self.engine = create_engine(
            self.connection_string,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 20,
            }
        )
        self.Session = sessionmaker(bind=self.engine)
        self.meta = MetaData()
        self._define_tables()
        print("[NHL SGP DB] Connection established.")

    def _define_tables(self):
        """Define NHL SGP table schemas."""

        # =====================================================================
        # NHL SGP Parlays (parent table)
        # =====================================================================
        self.nhl_sgp_parlays_table = Table('nhl_sgp_parlays', self.meta,
            Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column('parlay_type', String(50), nullable=False),  # 'primary', 'theme_stack', 'value_play'
            Column('game_id', String(100), nullable=False),      # e.g., '2025_NHL_TOR_MTL_20250115'
            Column('game_date', Date, nullable=False),
            Column('home_team', String(10), nullable=False),
            Column('away_team', String(10), nullable=False),
            Column('game_slot', String(20)),                     # 'EVENING', 'AFTERNOON', 'MATINEE'
            Column('total_legs', Integer, nullable=False),
            Column('combined_odds', Integer),                    # American odds (e.g., +450)
            Column('implied_probability', Numeric(6, 4)),
            Column('thesis', Text),                              # Narrative explanation
            Column('season', Integer, nullable=False),
            Column('season_type', String(20), default='regular'), # 'regular', 'playoffs'
            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
            Column('updated_at', TIMESTAMP, default=text("timezone('utc', now())")),

            UniqueConstraint('season', 'season_type', 'parlay_type', 'game_id',
                           name='uq_nhl_sgp_parlay')
        )

        # =====================================================================
        # NHL SGP Legs (individual props)
        # =====================================================================
        self.nhl_sgp_legs_table = Table('nhl_sgp_legs', self.meta,
            Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column('parlay_id', UUID(as_uuid=True), ForeignKey('nhl_sgp_parlays.id'), nullable=False),
            Column('leg_number', Integer, nullable=False),       # Order in parlay (1, 2, 3...)
            Column('player_name', String(100), nullable=False),
            Column('player_id', Integer),                        # NHL player_id if matched
            Column('team', String(10)),
            Column('position', String(10)),                      # C, LW, RW, D, G
            Column('stat_type', String(50), nullable=False),     # 'points', 'goals', 'assists', etc.
            Column('line', Numeric(6, 1)),                       # e.g., 0.5, 1.5
            Column('direction', String(10), nullable=False),     # 'over' or 'under'
            Column('odds', Integer),                             # American odds (e.g., -110)
            Column('edge_pct', Numeric(5, 2)),                   # Projected edge %
            Column('confidence', Numeric(3, 2)),                 # 0.0 to 1.0
            Column('model_probability', Numeric(6, 4)),          # Our model's win probability
            Column('market_probability', Numeric(6, 4)),         # Implied from odds
            Column('primary_reason', Text),                      # Main evidence statement
            Column('supporting_reasons', JSONB),                 # Array of strings
            Column('risk_factors', JSONB),                       # Array of strings
            Column('signals', JSONB),                            # Full signal breakdown

            # Pipeline context (from main NHL points system)
            Column('pipeline_score', Numeric(6, 2)),             # 0-100 from main pipeline
            Column('pipeline_confidence', String(20)),           # very_high, high, medium, low
            Column('pipeline_rank', Integer),                    # Daily rank from main pipeline

            # Settlement
            Column('actual_value', Numeric(6, 1)),               # Post-game actual stat
            Column('result', String(10)),                        # 'WIN', 'LOSS', 'PUSH', 'VOID'

            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),
        )

        # =====================================================================
        # NHL SGP Settlements
        # =====================================================================
        self.nhl_sgp_settlements_table = Table('nhl_sgp_settlements', self.meta,
            Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column('parlay_id', UUID(as_uuid=True), ForeignKey('nhl_sgp_parlays.id'), nullable=False),
            Column('legs_hit', Integer),
            Column('total_legs', Integer),
            Column('result', String(10)),                        # 'WIN', 'LOSS', 'VOID'
            Column('profit', Numeric(10, 2)),                    # At $100 stake
            Column('settled_at', TIMESTAMP),
            Column('notes', Text),
        )

        # =====================================================================
        # NHL SGP Historical Odds (for backtesting)
        # =====================================================================
        self.nhl_sgp_historical_odds_table = Table('nhl_sgp_historical_odds', self.meta,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('event_id', String(100), nullable=False),
            Column('game_date', Date, nullable=False),
            Column('home_team', String(10)),
            Column('away_team', String(10)),

            # Prop details
            Column('player_name', String(100), nullable=False),
            Column('player_id', Integer),                        # If matched to roster
            Column('stat_type', String(50), nullable=False),
            Column('market_key', String(50)),
            Column('line', Numeric(6, 2)),
            Column('over_price', Integer),                       # American odds
            Column('under_price', Integer),
            Column('bookmaker', String(50)),

            # Snapshot metadata
            Column('snapshot_time', TIMESTAMP),

            # Outcome (filled after settlement)
            Column('actual_value', Numeric(6, 2)),
            Column('over_hit', Boolean),
            Column('settled', Boolean, default=False),

            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),

            UniqueConstraint('event_id', 'player_name', 'stat_type', 'bookmaker', 'line',
                           name='uq_nhl_sgp_hist_odds')
        )

        # =====================================================================
        # NHL SGP Predictions (single prop bets for production)
        # =====================================================================
        self.nhl_sgp_predictions_table = Table('nhl_sgp_predictions', self.meta,
            Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column('game_date', Date, nullable=False),
            Column('event_id', String(100)),                      # Odds API event ID
            Column('game_id', Integer),                           # NHL API game ID
            Column('matchup', String(100)),                       # "Away@Home"
            Column('home_team', String(10)),
            Column('away_team', String(10)),

            # Prediction details
            Column('player_name', String(100), nullable=False),
            Column('player_id', Integer),                         # NHL player ID
            Column('team', String(10)),
            Column('market_key', String(50), nullable=False),     # 'player_points', 'player_shots_on_goal', etc.
            Column('stat_type', String(50), nullable=False),      # 'points', 'shots_on_goal', etc.
            Column('line', Numeric(6, 2), nullable=False),
            Column('direction', String(10), nullable=False),      # 'over' or 'under'
            Column('odds', Integer),                              # American odds

            # Edge calculation
            Column('edge_pct', Numeric(6, 2)),                    # Our edge %
            Column('model_probability', Numeric(6, 4)),           # Our model's probability
            Column('market_probability', Numeric(6, 4)),          # Implied from odds
            Column('confidence', Numeric(4, 2)),                  # 0.0 to 1.0
            Column('signals', JSONB),                             # Signal breakdown

            # Context
            Column('season_avg', Numeric(6, 2)),
            Column('recent_avg', Numeric(6, 2)),
            Column('primary_reason', Text),

            # Settlement
            Column('actual_value', Numeric(6, 2)),
            Column('hit', Boolean),                               # True = won, False = lost
            Column('settled', Boolean, default=False),
            Column('settled_at', TIMESTAMP),

            Column('created_at', TIMESTAMP, default=text("timezone('utc', now())")),

            UniqueConstraint('game_date', 'player_name', 'market_key', 'line', 'direction',
                           name='uq_nhl_sgp_prediction')
        )

        # Indexes
        Index('idx_nhl_sgp_parlays_date', self.nhl_sgp_parlays_table.c.game_date)
        Index('idx_nhl_sgp_legs_parlay', self.nhl_sgp_legs_table.c.parlay_id)
        Index('idx_nhl_sgp_hist_date', self.nhl_sgp_historical_odds_table.c.game_date)
        Index('idx_nhl_sgp_predictions_date', self.nhl_sgp_predictions_table.c.game_date)
        Index('idx_nhl_sgp_predictions_unsettled', self.nhl_sgp_predictions_table.c.settled)

    # =========================================================================
    # Schema Creation
    # =========================================================================

    def create_tables(self):
        """Create all NHL SGP tables if they don't exist."""
        with self.Session() as session:
            # Check if tables exist
            existing = session.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE 'nhl_sgp_%'
            """)).fetchall()
            existing_tables = [r[0] for r in existing]

            tables_to_create = [
                ('nhl_sgp_parlays', self.nhl_sgp_parlays_table),
                ('nhl_sgp_legs', self.nhl_sgp_legs_table),
                ('nhl_sgp_settlements', self.nhl_sgp_settlements_table),
                ('nhl_sgp_historical_odds', self.nhl_sgp_historical_odds_table),
                ('nhl_sgp_predictions', self.nhl_sgp_predictions_table),
            ]

            for table_name, table in tables_to_create:
                if table_name not in existing_tables:
                    print(f"[NHL SGP DB] Creating table: {table_name}")
                    table.create(self.engine, checkfirst=True)
                else:
                    print(f"[NHL SGP DB] Table exists: {table_name}")

            session.commit()
            print("[NHL SGP DB] Schema ready.")

    # =========================================================================
    # Parlay Operations
    # =========================================================================

    def upsert_parlay(self, parlay: Dict) -> str:
        """
        Insert or update a parlay record.

        Args:
            parlay: Dict with parlay fields

        Returns:
            Parlay ID (UUID string)
        """
        with self.Session() as session:
            stmt = insert(self.nhl_sgp_parlays_table).values(**parlay)
            stmt = stmt.on_conflict_do_update(
                constraint='uq_nhl_sgp_parlay',
                set_={
                    'total_legs': stmt.excluded.total_legs,
                    'combined_odds': stmt.excluded.combined_odds,
                    'implied_probability': stmt.excluded.implied_probability,
                    'thesis': stmt.excluded.thesis,
                    'updated_at': text("timezone('utc', now())"),
                }
            )
            result = session.execute(stmt)
            session.commit()

            # Get the parlay ID
            query = session.execute(
                self.nhl_sgp_parlays_table.select().where(
                    (self.nhl_sgp_parlays_table.c.season == parlay['season']) &
                    (self.nhl_sgp_parlays_table.c.parlay_type == parlay['parlay_type']) &
                    (self.nhl_sgp_parlays_table.c.game_id == parlay['game_id'])
                )
            )
            row = query.fetchone()
            return str(row.id) if row else None

    def upsert_legs(self, parlay_id: str, legs: List[Dict]):
        """
        Insert or update legs for a parlay.
        Deletes existing legs and inserts new ones.

        Args:
            parlay_id: UUID of parent parlay
            legs: List of leg dictionaries
        """
        with self.Session() as session:
            # Delete existing legs
            session.execute(
                self.nhl_sgp_legs_table.delete().where(
                    self.nhl_sgp_legs_table.c.parlay_id == parlay_id
                )
            )

            # Insert new legs
            for leg in legs:
                leg['parlay_id'] = parlay_id
                if 'id' not in leg:
                    leg['id'] = uuid.uuid4()
                session.execute(
                    self.nhl_sgp_legs_table.insert().values(**leg)
                )

            session.commit()
            print(f"[NHL SGP DB] Upserted {len(legs)} legs for parlay {parlay_id[:8]}...")

    # =========================================================================
    # Historical Odds Operations
    # =========================================================================

    def bulk_insert_historical_odds(self, odds_records: List[Dict]) -> int:
        """
        Bulk insert historical odds records (for backtesting).

        Args:
            odds_records: List of odds record dictionaries

        Returns:
            Number of records inserted
        """
        if not odds_records:
            return 0

        with self.Session() as session:
            # Use ON CONFLICT DO NOTHING to skip duplicates
            stmt = insert(self.nhl_sgp_historical_odds_table)
            stmt = stmt.on_conflict_do_nothing(constraint='uq_nhl_sgp_hist_odds')

            session.execute(stmt, odds_records)
            session.commit()

        return len(odds_records)

    def get_unsettled_historical_odds(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> List[Dict]:
        """Get historical odds records that haven't been settled."""
        with self.Session() as session:
            query = self.nhl_sgp_historical_odds_table.select().where(
                self.nhl_sgp_historical_odds_table.c.settled == False
            )

            if start_date:
                query = query.where(
                    self.nhl_sgp_historical_odds_table.c.game_date >= start_date
                )
            if end_date:
                query = query.where(
                    self.nhl_sgp_historical_odds_table.c.game_date <= end_date
                )

            result = session.execute(query)
            return [dict(row._mapping) for row in result]

    def settle_historical_odds(self, settlements: List[Dict]):
        """
        Update historical odds with actual outcomes.

        Args:
            settlements: List of dicts with id, actual_value, over_hit
        """
        with self.Session() as session:
            for s in settlements:
                session.execute(
                    self.nhl_sgp_historical_odds_table.update().where(
                        self.nhl_sgp_historical_odds_table.c.id == s['id']
                    ).values(
                        actual_value=s['actual_value'],
                        over_hit=s['over_hit'],
                        settled=True,
                    )
                )
            session.commit()
            print(f"[NHL SGP DB] Settled {len(settlements)} historical odds records.")

    # =========================================================================
    # Query Operations
    # =========================================================================

    def get_settlement_for_parlay(self, parlay_id: str) -> Optional[Dict]:
        """Check if a parlay has been settled."""
        with self.Session() as session:
            # Convert string to UUID if needed
            parlay_uuid = uuid.UUID(parlay_id) if isinstance(parlay_id, str) else parlay_id

            result = session.execute(
                self.nhl_sgp_settlements_table.select().where(
                    self.nhl_sgp_settlements_table.c.parlay_id == parlay_uuid
                )
            )
            row = result.fetchone()
            if row:
                return dict(row._mapping)
            return None

    def get_settlements_by_date(self, game_date: date) -> List[Dict]:
        """Get all settlements for parlays on a specific date."""
        with self.Session() as session:
            result = session.execute(text("""
                SELECT
                    s.id::text as id,
                    s.parlay_id::text as parlay_id,
                    s.legs_hit,
                    s.total_legs,
                    s.result,
                    s.profit::float,
                    s.settled_at,
                    s.notes,
                    p.parlay_type,
                    p.game_id,
                    p.home_team,
                    p.away_team,
                    p.combined_odds
                FROM nhl_sgp_settlements s
                JOIN nhl_sgp_parlays p ON s.parlay_id = p.id
                WHERE p.game_date = :game_date
                ORDER BY s.settled_at DESC
            """), {'game_date': game_date})

            return [dict(row._mapping) for row in result]

    def get_parlays_by_date(self, game_date: date) -> List[Dict]:
        """Get all parlays for a specific date with legs."""
        with self.Session() as session:
            result = session.execute(text("""
                SELECT
                    p.id::text as id,
                    p.parlay_type,
                    p.game_id,
                    p.game_date,
                    p.home_team,
                    p.away_team,
                    p.game_slot,
                    p.total_legs,
                    p.combined_odds,
                    p.implied_probability::float,
                    p.thesis,
                    p.season,
                    p.season_type,
                    p.created_at,
                    p.updated_at,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'id', l.id::text,
                                'leg_number', l.leg_number,
                                'player_name', l.player_name,
                                'player_id', l.player_id,
                                'team', l.team,
                                'position', l.position,
                                'stat_type', l.stat_type,
                                'line', l.line::float,
                                'direction', l.direction,
                                'odds', l.odds,
                                'edge_pct', l.edge_pct::float,
                                'confidence', l.confidence::float,
                                'model_probability', l.model_probability::float,
                                'market_probability', l.market_probability::float,
                                'primary_reason', l.primary_reason,
                                'supporting_reasons', l.supporting_reasons,
                                'risk_factors', l.risk_factors,
                                'signals', l.signals,
                                'actual_value', l.actual_value::float,
                                'result', l.result,
                                'created_at', l.created_at
                            ) ORDER BY l.leg_number
                        ) FILTER (WHERE l.id IS NOT NULL),
                        '[]'::json
                    ) as legs
                FROM nhl_sgp_parlays p
                LEFT JOIN nhl_sgp_legs l ON p.id = l.parlay_id
                WHERE p.game_date = :game_date
                GROUP BY p.id
                ORDER BY p.created_at DESC
            """), {'game_date': game_date})

            return [dict(row._mapping) for row in result]

    def get_backtest_performance(
        self,
        start_date: date = None,
        end_date: date = None,
        min_edge: float = 0,
    ) -> Dict:
        """
        Get backtest performance metrics from historical odds.

        Returns hit rates by edge bucket and overall ROI.
        """
        with self.Session() as session:
            # Build filter
            filters = ["settled = true"]
            params = {}

            if start_date:
                filters.append("game_date >= :start_date")
                params['start_date'] = start_date
            if end_date:
                filters.append("game_date <= :end_date")
                params['end_date'] = end_date

            where_clause = " AND ".join(filters)

            result = session.execute(text(f"""
                SELECT
                    COUNT(*) as total_props,
                    SUM(CASE WHEN over_hit = true THEN 1 ELSE 0 END) as over_hits,
                    SUM(CASE WHEN over_hit = false THEN 1 ELSE 0 END) as under_hits,
                    AVG(CASE WHEN over_hit = true THEN 1.0 ELSE 0.0 END) as over_hit_rate
                FROM nhl_sgp_historical_odds
                WHERE {where_clause}
            """), params)

            row = result.fetchone()
            if not row:
                return {'total_props': 0}

            return {
                'total_props': row.total_props,
                'over_hits': row.over_hits,
                'under_hits': row.under_hits,
                'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else 0,
            }

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.Session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"[NHL SGP DB] Connection test failed: {e}")
            return False

    # =========================================================================
    # Prediction Operations (DEPRECATED - use parlays/legs instead)
    # =========================================================================

    def upsert_prediction(self, prediction: Dict) -> str:
        """
        DEPRECATED: Use upsert_parlay() and upsert_legs() instead.

        Insert or update a single prop prediction.

        Args:
            prediction: Dict with prediction fields

        Returns:
            Prediction ID (UUID string)
        """
        import warnings
        warnings.warn(
            "upsert_prediction is deprecated. Use upsert_parlay() and upsert_legs() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        with self.Session() as session:
            stmt = insert(self.nhl_sgp_predictions_table).values(**prediction)
            stmt = stmt.on_conflict_do_update(
                constraint='uq_nhl_sgp_prediction',
                set_={
                    'odds': stmt.excluded.odds,
                    'edge_pct': stmt.excluded.edge_pct,
                    'model_probability': stmt.excluded.model_probability,
                    'market_probability': stmt.excluded.market_probability,
                    'confidence': stmt.excluded.confidence,
                    'signals': stmt.excluded.signals,
                    'season_avg': stmt.excluded.season_avg,
                    'recent_avg': stmt.excluded.recent_avg,
                    'primary_reason': stmt.excluded.primary_reason,
                }
            )
            session.execute(stmt)
            session.commit()

            # Get the prediction ID
            query = session.execute(
                self.nhl_sgp_predictions_table.select().where(
                    (self.nhl_sgp_predictions_table.c.game_date == prediction['game_date']) &
                    (self.nhl_sgp_predictions_table.c.player_name == prediction['player_name']) &
                    (self.nhl_sgp_predictions_table.c.market_key == prediction['market_key']) &
                    (self.nhl_sgp_predictions_table.c.line == prediction['line']) &
                    (self.nhl_sgp_predictions_table.c.direction == prediction['direction'])
                )
            )
            row = query.fetchone()
            return str(row.id) if row else None

    def bulk_upsert_predictions(self, predictions: List[Dict]) -> int:
        """
        Bulk insert/update predictions.

        Returns:
            Number of predictions upserted
        """
        if not predictions:
            return 0

        count = 0
        for pred in predictions:
            try:
                self.upsert_prediction(pred)
                count += 1
            except Exception as e:
                print(f"[NHL SGP DB] Error upserting prediction: {e}")

        print(f"[NHL SGP DB] Upserted {count} predictions")
        return count

    def get_unsettled_predictions(self, game_date: date = None) -> List[Dict]:
        """Get predictions that haven't been settled yet."""
        with self.Session() as session:
            query = self.nhl_sgp_predictions_table.select().where(
                self.nhl_sgp_predictions_table.c.settled == False
            )

            if game_date:
                query = query.where(
                    self.nhl_sgp_predictions_table.c.game_date == game_date
                )

            result = session.execute(query)
            return [dict(row._mapping) for row in result]

    def settle_predictions(self, settlements: List[Dict]) -> int:
        """
        Settle predictions with actual results.

        Args:
            settlements: List of dicts with id, actual_value, hit

        Returns:
            Number of predictions settled
        """
        with self.Session() as session:
            count = 0
            for s in settlements:
                session.execute(
                    self.nhl_sgp_predictions_table.update().where(
                        self.nhl_sgp_predictions_table.c.id == s['id']
                    ).values(
                        actual_value=s.get('actual_value'),
                        hit=s.get('hit'),
                        settled=True,
                        settled_at=text("timezone('utc', now())"),
                    )
                )
                count += 1
            session.commit()
            print(f"[NHL SGP DB] Settled {count} predictions")
            return count

    def get_predictions_by_date(self, game_date: date) -> List[Dict]:
        """Get all predictions for a specific date."""
        with self.Session() as session:
            result = session.execute(
                self.nhl_sgp_predictions_table.select().where(
                    self.nhl_sgp_predictions_table.c.game_date == game_date
                ).order_by(
                    self.nhl_sgp_predictions_table.c.edge_pct.desc()
                )
            )
            return [dict(row._mapping) for row in result]

    def get_prediction_performance(
        self,
        start_date: date = None,
        end_date: date = None,
        min_edge: float = None,
        market_key: str = None,
    ) -> Dict:
        """
        Get prediction performance metrics.

        Returns hit rates by edge bucket and market.
        """
        with self.Session() as session:
            filters = ["settled = true"]
            params = {}

            if start_date:
                filters.append("game_date >= :start_date")
                params['start_date'] = start_date
            if end_date:
                filters.append("game_date <= :end_date")
                params['end_date'] = end_date
            if min_edge is not None:
                filters.append("edge_pct >= :min_edge")
                params['min_edge'] = min_edge
            if market_key:
                filters.append("market_key = :market_key")
                params['market_key'] = market_key

            where_clause = " AND ".join(filters)

            result = session.execute(text(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN hit = true THEN 1 ELSE 0 END) as hits,
                    AVG(CASE WHEN hit = true THEN 1.0 ELSE 0.0 END) as hit_rate,
                    AVG(edge_pct) as avg_edge
                FROM nhl_sgp_predictions
                WHERE {where_clause}
            """), params)

            row = result.fetchone()
            if not row or row.total == 0:
                return {'total': 0}

            return {
                'total': row.total,
                'hits': row.hits,
                'hit_rate': float(row.hit_rate) if row.hit_rate else 0,
                'avg_edge': float(row.avg_edge) if row.avg_edge else 0,
            }
