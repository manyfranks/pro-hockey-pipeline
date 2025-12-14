-- NHL SGP Engine Database Migration
-- Version: 1.0
-- Date: December 13, 2025
--
-- Creates the NHL SGP tables aligned with NFL/NCAAF SGP architecture:
-- 1. nhl_sgp_parlays - Parent parlay records
-- 2. nhl_sgp_legs - Individual prop legs
-- 3. nhl_sgp_settlements - Settlement records
-- 4. nhl_sgp_historical_odds - Backtesting cache (optional)
--
-- Run this in Supabase SQL Editor

-- =============================================================================
-- Enable UUID extension if not already enabled
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Table: nhl_sgp_parlays
-- Parent record for each parlay recommendation
-- =============================================================================
CREATE TABLE IF NOT EXISTS nhl_sgp_parlays (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Parlay classification
    parlay_type VARCHAR(50) NOT NULL,  -- 'primary', 'theme_stack', 'value_play'

    -- Game identification
    game_id VARCHAR(100) NOT NULL,      -- e.g., '2025_NHL_TOR_MTL_20251214'
    game_date DATE NOT NULL,
    home_team VARCHAR(10) NOT NULL,
    away_team VARCHAR(10) NOT NULL,
    game_slot VARCHAR(20),              -- 'EVENING', 'AFTERNOON', 'MATINEE'

    -- Parlay details
    total_legs INTEGER NOT NULL,
    combined_odds INTEGER,              -- American odds (e.g., +450)
    implied_probability DECIMAL(6, 4),
    thesis TEXT,                        -- Narrative explanation

    -- Season tracking
    season INTEGER NOT NULL,
    season_type VARCHAR(20) DEFAULT 'regular',  -- 'regular', 'playoffs'

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()),

    -- Unique constraint (one parlay per type per game)
    CONSTRAINT uq_nhl_sgp_parlay UNIQUE (season, season_type, parlay_type, game_id)
);

-- Index for date-based queries
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_parlays_date ON nhl_sgp_parlays(game_date);
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_parlays_type ON nhl_sgp_parlays(parlay_type);

-- =============================================================================
-- Table: nhl_sgp_legs
-- Individual legs within each parlay
-- =============================================================================
CREATE TABLE IF NOT EXISTS nhl_sgp_legs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Parent relationship
    parlay_id UUID NOT NULL REFERENCES nhl_sgp_parlays(id) ON DELETE CASCADE,
    leg_number INTEGER NOT NULL,        -- Order within parlay (1, 2, 3...)

    -- Player identification
    player_name VARCHAR(100) NOT NULL,
    player_id INTEGER,                  -- NHL API player_id
    team VARCHAR(10),
    position VARCHAR(10),               -- C, LW, RW, D, G

    -- Prop details
    stat_type VARCHAR(50) NOT NULL,     -- 'points', 'shots_on_goal', etc.
    line DECIMAL(6, 1),                 -- e.g., 0.5, 3.5
    direction VARCHAR(10) NOT NULL,     -- 'over' or 'under'
    odds INTEGER,                       -- American odds (e.g., -110)

    -- Edge calculation
    edge_pct DECIMAL(5, 2),             -- Projected edge percentage
    confidence DECIMAL(3, 2),           -- 0.0 to 1.0
    model_probability DECIMAL(6, 4),    -- Our model's win probability
    market_probability DECIMAL(6, 4),   -- Implied from odds

    -- Evidence
    primary_reason TEXT,                -- Main evidence statement
    supporting_reasons JSONB,           -- Array of strings
    risk_factors JSONB,                 -- Array of strings
    signals JSONB,                      -- Full signal breakdown

    -- Pipeline integration (from main NHL points system)
    pipeline_score DECIMAL(6, 2),       -- 0-100 from main pipeline
    pipeline_confidence VARCHAR(20),    -- very_high, high, medium, low
    pipeline_rank INTEGER,              -- Daily rank from main pipeline

    -- Settlement (filled post-game)
    actual_value DECIMAL(6, 1),         -- Post-game actual stat
    result VARCHAR(10),                 -- 'WIN', 'LOSS', 'PUSH', 'VOID'

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now())
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_legs_parlay ON nhl_sgp_legs(parlay_id);
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_legs_player ON nhl_sgp_legs(player_name);
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_legs_result ON nhl_sgp_legs(result);

-- =============================================================================
-- Table: nhl_sgp_settlements
-- Settlement records for tracking parlay outcomes
-- =============================================================================
CREATE TABLE IF NOT EXISTS nhl_sgp_settlements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Parent relationship
    parlay_id UUID NOT NULL REFERENCES nhl_sgp_parlays(id) ON DELETE CASCADE,

    -- Settlement details
    legs_hit INTEGER,                   -- Number of legs that hit
    total_legs INTEGER,                 -- Total legs (excluding VOIDs)
    result VARCHAR(10),                 -- 'WIN', 'LOSS', 'VOID'
    profit DECIMAL(10, 2),              -- Profit at $100 stake

    -- Timestamps
    settled_at TIMESTAMP WITH TIME ZONE,
    notes TEXT
);

-- Index
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_settlements_parlay ON nhl_sgp_settlements(parlay_id);
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_settlements_result ON nhl_sgp_settlements(result);

-- =============================================================================
-- Table: nhl_sgp_historical_odds
-- Historical odds cache for backtesting (not used in production)
-- =============================================================================
CREATE TABLE IF NOT EXISTS nhl_sgp_historical_odds (
    id SERIAL PRIMARY KEY,

    -- Event identification
    event_id VARCHAR(100) NOT NULL,
    game_date DATE NOT NULL,
    home_team VARCHAR(10),
    away_team VARCHAR(10),

    -- Prop details
    player_name VARCHAR(100) NOT NULL,
    player_id INTEGER,                  -- NHL API player_id if matched
    stat_type VARCHAR(50) NOT NULL,
    market_key VARCHAR(50),
    line DECIMAL(6, 2),
    over_price INTEGER,                 -- American odds
    under_price INTEGER,
    bookmaker VARCHAR(50),

    -- Snapshot metadata
    snapshot_time TIMESTAMP WITH TIME ZONE,

    -- Outcome (filled after settlement)
    actual_value DECIMAL(6, 2),
    over_hit BOOLEAN,
    settled BOOLEAN DEFAULT false,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()),

    -- Unique constraint
    CONSTRAINT uq_nhl_sgp_hist_odds UNIQUE (event_id, player_name, stat_type, bookmaker, line)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_hist_date ON nhl_sgp_historical_odds(game_date);
CREATE INDEX IF NOT EXISTS idx_nhl_sgp_hist_settled ON nhl_sgp_historical_odds(settled);

-- =============================================================================
-- Views for reporting
-- =============================================================================

-- View: Today's parlays with legs
CREATE OR REPLACE VIEW v_nhl_sgp_today AS
SELECT
    p.id,
    p.parlay_type,
    p.away_team || ' @ ' || p.home_team as matchup,
    p.combined_odds,
    p.thesis,
    p.total_legs,
    json_agg(
        json_build_object(
            'leg_number', l.leg_number,
            'player_name', l.player_name,
            'stat_type', l.stat_type,
            'line', l.line,
            'direction', l.direction,
            'odds', l.odds,
            'edge_pct', l.edge_pct,
            'primary_reason', l.primary_reason
        ) ORDER BY l.leg_number
    ) as legs
FROM nhl_sgp_parlays p
JOIN nhl_sgp_legs l ON p.id = l.parlay_id
WHERE p.game_date = CURRENT_DATE
GROUP BY p.id
ORDER BY p.created_at DESC;

-- View: Performance summary
CREATE OR REPLACE VIEW v_nhl_sgp_performance AS
SELECT
    p.parlay_type,
    COUNT(DISTINCT p.id) as total_parlays,
    SUM(CASE WHEN s.result = 'WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN s.result = 'LOSS' THEN 1 ELSE 0 END) as losses,
    ROUND(
        AVG(CASE WHEN s.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1
    ) as win_rate_pct,
    ROUND(AVG(l.edge_pct), 2) as avg_edge,
    SUM(COALESCE(s.profit, 0)) as total_profit
FROM nhl_sgp_parlays p
LEFT JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
LEFT JOIN nhl_sgp_legs l ON p.id = l.parlay_id
WHERE s.result IS NOT NULL
GROUP BY p.parlay_type
ORDER BY total_parlays DESC;

-- View: Leg hit rates by market
CREATE OR REPLACE VIEW v_nhl_sgp_leg_performance AS
SELECT
    l.stat_type,
    COUNT(*) as total_legs,
    SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as wins,
    ROUND(
        AVG(CASE WHEN l.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1
    ) as hit_rate_pct,
    ROUND(AVG(l.edge_pct), 2) as avg_edge
FROM nhl_sgp_legs l
WHERE l.result IS NOT NULL
GROUP BY l.stat_type
ORDER BY total_legs DESC;

-- =============================================================================
-- RLS Policies (Row Level Security)
-- =============================================================================

-- Enable RLS
ALTER TABLE nhl_sgp_parlays ENABLE ROW LEVEL SECURITY;
ALTER TABLE nhl_sgp_legs ENABLE ROW LEVEL SECURITY;
ALTER TABLE nhl_sgp_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE nhl_sgp_historical_odds ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (for idempotent migrations)
DROP POLICY IF EXISTS "Allow anonymous read access on parlays" ON nhl_sgp_parlays;
DROP POLICY IF EXISTS "Allow anonymous read access on legs" ON nhl_sgp_legs;
DROP POLICY IF EXISTS "Allow anonymous read access on settlements" ON nhl_sgp_settlements;
DROP POLICY IF EXISTS "Allow anonymous read access on historical_odds" ON nhl_sgp_historical_odds;

-- Allow anonymous read access
CREATE POLICY "Allow anonymous read access on parlays"
    ON nhl_sgp_parlays FOR SELECT
    USING (true);

CREATE POLICY "Allow anonymous read access on legs"
    ON nhl_sgp_legs FOR SELECT
    USING (true);

CREATE POLICY "Allow anonymous read access on settlements"
    ON nhl_sgp_settlements FOR SELECT
    USING (true);

CREATE POLICY "Allow anonymous read access on historical_odds"
    ON nhl_sgp_historical_odds FOR SELECT
    USING (true);

-- Service role has full access (automatically via bypass)

-- =============================================================================
-- Comments for documentation
-- =============================================================================

COMMENT ON TABLE nhl_sgp_parlays IS 'NHL Same Game Parlay recommendations';
COMMENT ON TABLE nhl_sgp_legs IS 'Individual legs within NHL SGP parlays';
COMMENT ON TABLE nhl_sgp_settlements IS 'Settlement records for NHL SGP parlays';
COMMENT ON TABLE nhl_sgp_historical_odds IS 'Historical odds cache for backtesting';

COMMENT ON COLUMN nhl_sgp_parlays.parlay_type IS 'primary=best edge, theme_stack=correlated legs, value_play=high-risk';
COMMENT ON COLUMN nhl_sgp_parlays.combined_odds IS 'American odds format (e.g., +450 or -150)';
COMMENT ON COLUMN nhl_sgp_parlays.thesis IS 'Narrative explanation of why this parlay makes sense';

COMMENT ON COLUMN nhl_sgp_legs.signals IS 'JSONB with line_value, trend, usage, matchup, environment, correlation signals';
COMMENT ON COLUMN nhl_sgp_legs.pipeline_score IS 'Integration with main NHL points prediction system';

-- =============================================================================
-- Cleanup: Drop deprecated nhl_sgp_predictions table if exists
-- (This table was incorrectly added in earlier implementation)
-- =============================================================================

-- Uncomment to drop the deprecated table:
-- DROP TABLE IF EXISTS nhl_sgp_predictions CASCADE;

-- =============================================================================
-- RPC Functions for Frontend
-- =============================================================================

-- Drop existing function if exists (for clean recreation)
DROP FUNCTION IF EXISTS get_nhl_sgp_performance(DATE, DATE);

-- Function: Get NHL SGP performance stats
CREATE OR REPLACE FUNCTION get_nhl_sgp_performance(
    start_date DATE DEFAULT NULL,
    end_date DATE DEFAULT NULL
)
RETURNS JSON
LANGUAGE plpgsql
AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'total_parlays', COUNT(DISTINCT p.id),
        'wins', SUM(CASE WHEN s.result = 'WIN' THEN 1 ELSE 0 END),
        'losses', SUM(CASE WHEN s.result = 'LOSS' THEN 1 ELSE 0 END),
        'win_rate', ROUND(
            AVG(CASE WHEN s.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1
        ),
        'total_legs', (SELECT COUNT(*) FROM nhl_sgp_legs l2
                       JOIN nhl_sgp_parlays p2 ON l2.parlay_id = p2.id
                       WHERE (start_date IS NULL OR p2.game_date >= start_date)
                       AND (end_date IS NULL OR p2.game_date <= end_date)
                       AND l2.result IS NOT NULL),
        'legs_hit', (SELECT SUM(CASE WHEN l2.result = 'WIN' THEN 1 ELSE 0 END)
                     FROM nhl_sgp_legs l2
                     JOIN nhl_sgp_parlays p2 ON l2.parlay_id = p2.id
                     WHERE (start_date IS NULL OR p2.game_date >= start_date)
                     AND (end_date IS NULL OR p2.game_date <= end_date)
                     AND l2.result IS NOT NULL),
        'leg_hit_rate', (SELECT ROUND(
            AVG(CASE WHEN l2.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1
        ) FROM nhl_sgp_legs l2
          JOIN nhl_sgp_parlays p2 ON l2.parlay_id = p2.id
          WHERE (start_date IS NULL OR p2.game_date >= start_date)
          AND (end_date IS NULL OR p2.game_date <= end_date)
          AND l2.result IS NOT NULL),
        'total_profit', COALESCE(SUM(s.profit), 0),
        'avg_odds', ROUND(AVG(p.combined_odds))
    ) INTO result
    FROM nhl_sgp_parlays p
    JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
    WHERE (start_date IS NULL OR p.game_date >= start_date)
    AND (end_date IS NULL OR p.game_date <= end_date);

    RETURN result;
END;
$$;

-- Grant execute to anon role
GRANT EXECUTE ON FUNCTION get_nhl_sgp_performance(DATE, DATE) TO anon;
GRANT EXECUTE ON FUNCTION get_nhl_sgp_performance(DATE, DATE) TO authenticated;

-- =============================================================================
-- Verification
-- =============================================================================

-- Check tables were created
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name LIKE 'nhl_sgp_%'
ORDER BY table_name;
