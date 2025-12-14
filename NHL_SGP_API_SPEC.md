# NHL SGP Engine API Specification

**Version:** 1.1
**Last Updated:** December 14, 2025
**Base URL:** `https://[project-id].supabase.co/rest/v1`

> **Changelog v1.1**: Fixed data type serialization in query responses. UUIDs are now returned as strings, Decimals as floats. Added duplicate settlement check. Added `get_settlements_by_date` and `get_settlement_for_parlay` methods.

---

## Table of Contents

1. [Overview](#overview)
2. [Database Tables](#database-tables)
3. [API Endpoints](#api-endpoints)
4. [Data Models](#data-models)
5. [Query Examples](#query-examples)
6. [Production Schedule](#production-schedule)

---

## Overview

The NHL SGP (Same Game Parlay) Engine generates optimized multi-leg parlay recommendations for NHL games using a 6-signal analytical framework. Architecture mirrors NFL/NCAAF SGP implementations for consistency across leagues.

### Key Features

- **Daily Parlay Generation**: Automatic generation for each game day
- **6-Signal Framework**: Line value, trend, usage, matchup, environment, correlation
- **Multi-Leg Optimization**: 3-4 legs per parlay with correlation checking
- **Settlement Tracking**: Win/loss tracking with actual box score values
- **Validated Markets**: player_points, player_shots_on_goal (10-15% edge = 49.6% hit rate)

### Signal Weights

| Signal | Weight | Description |
|--------|--------|-------------|
| Line Value | 35% | Season average vs prop line comparison |
| Trend | 15% | Last 5 games vs season average |
| Usage | 10% | TOI, PP time, line deployment |
| Matchup | 15% | Opponent defensive quality |
| Environment | 15% | Game script, venue, spread, total |
| Correlation | 10% | Prop correlation with game outcome |

### Validated Markets (from November Backtest)

| Market | Edge 10-15% Hit Rate | Positive Edge % | Recommended |
|--------|---------------------|-----------------|-------------|
| player_points | 49.6% | 71.0% | YES |
| player_shots_on_goal | 50.1% | 75.8% | YES |
| player_blocked_shots | 44.4% | N/A (no positive edge) | NO |
| player_assists | 32.6% | 72.6% | NO (low hit rate) |
| player_goal_scorer_anytime | 15.4% | 31.0% | NO |

---

## Database Tables

### `nhl_sgp_parlays`

Parent table storing parlay recommendations.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `a1b2c3d4-...` |
| `parlay_type` | VARCHAR(50) | Parlay category | `primary`, `theme_stack`, `value_play` |
| `game_id` | VARCHAR(100) | Unique game identifier | `2025_NHL_TOR_MTL_20250115` |
| `game_date` | DATE | Game date | `2025-12-14` |
| `home_team` | VARCHAR(10) | Home team abbreviation | `MTL` |
| `away_team` | VARCHAR(10) | Away team abbreviation | `TOR` |
| `game_slot` | VARCHAR(20) | Time slot | `EVENING`, `AFTERNOON`, `MATINEE` |
| `total_legs` | INTEGER | Number of legs | `3`, `4` |
| `combined_odds` | INTEGER | American odds | `+450`, `+823` |
| `implied_probability` | DECIMAL(6,4) | Win probability | `0.1818` |
| `thesis` | TEXT | Narrative explanation | `High-scoring rivalry game...` |
| `season` | INTEGER | NHL season year | `2025` |
| `season_type` | VARCHAR(20) | Season phase | `regular`, `playoffs` |
| `created_at` | TIMESTAMP | Creation time | `2025-12-14T10:00:00Z` |
| `updated_at` | TIMESTAMP | Last update | `2025-12-14T10:00:00Z` |

**Unique Constraint:** `(season, season_type, parlay_type, game_id)`

---

### `nhl_sgp_legs`

Individual legs within each parlay.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `b2c3d4e5-...` |
| `parlay_id` | UUID | FK to parlays | `a1b2c3d4-...` |
| `leg_number` | INTEGER | Order in parlay | `1`, `2`, `3` |
| `player_name` | VARCHAR(100) | Player display name | `Auston Matthews` |
| `player_id` | INTEGER | NHL player ID | `8479318` |
| `team` | VARCHAR(10) | Player's team | `TOR` |
| `position` | VARCHAR(10) | Position code | `C`, `LW`, `RW`, `D`, `G` |
| `stat_type` | VARCHAR(50) | Prop type | `points`, `shots_on_goal` |
| `line` | DECIMAL(6,1) | Prop line | `0.5`, `3.5` |
| `direction` | VARCHAR(10) | Over/under | `over`, `under` |
| `odds` | INTEGER | American odds | `-110`, `+105` |
| `edge_pct` | DECIMAL(5,2) | Projected edge | `12.5` |
| `confidence` | DECIMAL(3,2) | Confidence score | `0.78` |
| `model_probability` | DECIMAL(6,4) | Model win prob | `0.5842` |
| `market_probability` | DECIMAL(6,4) | Implied prob | `0.4762` |
| `primary_reason` | TEXT | Main evidence | `Season avg 1.2 pts vs 0.5 line` |
| `supporting_reasons` | JSONB | Additional reasons | `["L5 trending up"]` |
| `risk_factors` | JSONB | Risk warnings | `["B2B game"]` |
| `signals` | JSONB | Full signal breakdown | See Signal Object |
| `actual_value` | DECIMAL(6,1) | Post-game actual | `2.0` |
| `result` | VARCHAR(10) | Settlement result | `WIN`, `LOSS`, `PUSH`, `VOID` |
| `created_at` | TIMESTAMP | Creation time | `2025-12-14T10:00:00Z` |

**Foreign Key:** `parlay_id` references `nhl_sgp_parlays(id)`

---

### `nhl_sgp_settlements`

Settlement records for completed parlays.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `c3d4e5f6-...` |
| `parlay_id` | UUID | FK to parlays | `a1b2c3d4-...` |
| `legs_hit` | INTEGER | Legs that hit | `3` |
| `total_legs` | INTEGER | Total scoreable legs | `4` |
| `result` | VARCHAR(10) | Parlay result | `WIN`, `LOSS`, `VOID` |
| `profit` | DECIMAL(10,2) | At $100 stake | `450.00`, `-100.00` |
| `settled_at` | TIMESTAMP | Settlement time | `2025-12-15T08:00:00Z` |
| `notes` | TEXT | Settlement notes | `Settled automatically` |

---

### `nhl_sgp_historical_odds`

Historical odds cache for backtesting (not for production).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `event_id` | VARCHAR(100) | Odds API event ID |
| `game_date` | DATE | Game date |
| `home_team` | VARCHAR(10) | Home team |
| `away_team` | VARCHAR(10) | Away team |
| `player_name` | VARCHAR(100) | Player name |
| `stat_type` | VARCHAR(50) | Prop type |
| `market_key` | VARCHAR(50) | Odds API market key |
| `line` | DECIMAL(6,2) | Prop line |
| `over_price` | INTEGER | Over odds |
| `under_price` | INTEGER | Under odds |
| `bookmaker` | VARCHAR(50) | Sportsbook |
| `actual_value` | DECIMAL(6,2) | Post-game actual |
| `over_hit` | BOOLEAN | Did over hit |
| `settled` | BOOLEAN | Is settled |

---

## API Endpoints

### Get Today's Parlays

```http
GET /nhl_sgp_parlays?game_date=eq.2025-12-14&select=*,nhl_sgp_legs(*)
```

**Response:**
```json
[
  {
    "id": "a1b2c3d4-1111-4000-8000-000000000001",
    "parlay_type": "primary",
    "game_id": "2025_NHL_TOR_MTL_20251214",
    "game_date": "2025-12-14",
    "home_team": "MTL",
    "away_team": "TOR",
    "total_legs": 3,
    "combined_odds": 450,
    "implied_probability": 0.1818,
    "thesis": "High-scoring rivalry game favors offensive production...",
    "nhl_sgp_legs": [
      {
        "leg_number": 1,
        "player_name": "Auston Matthews",
        "stat_type": "points",
        "line": 0.5,
        "direction": "over",
        "odds": -135,
        "edge_pct": 12.5,
        "confidence": 0.78,
        "primary_reason": "Season avg 1.2 pts is 140% above 0.5 line"
      }
    ]
  }
]
```

### Get Parlays by Parlay Type

```http
GET /nhl_sgp_parlays?parlay_type=eq.primary&select=*,nhl_sgp_legs(*)&order=game_date.desc
```

### Get High-Edge Legs

```http
GET /nhl_sgp_legs?edge_pct=gte.10&order=edge_pct.desc&limit=20
```

### Get Settled Parlays

```http
GET /nhl_sgp_parlays?select=*,nhl_sgp_legs(*),nhl_sgp_settlements(*)
  &nhl_sgp_settlements.result=not.is.null
```

---

## Data Models

### Signal Object

The `signals` JSONB column contains the full signal breakdown:

```json
{
  "line_value": {
    "evidence": "Season avg 1.2 is 140% ABOVE line 0.5 (strong edge)",
    "strength": 0.95,
    "confidence": 0.90
  },
  "trend": {
    "evidence": "L5 avg 1.4 vs season 1.2 (UP 16.7%)",
    "strength": 0.17,
    "confidence": 0.80
  },
  "usage": {
    "evidence": "PP1 deployment, 22:30 TOI/gm",
    "strength": 0.15,
    "confidence": 0.85
  },
  "matchup": {
    "evidence": "MTL allows 3.4 goals/gm (bottom 10)",
    "strength": 0.20,
    "confidence": 0.75
  },
  "environment": {
    "evidence": "High total (6.5) = offensive game",
    "strength": 0.10,
    "confidence": 0.70
  },
  "correlation": {
    "evidence": "Points correlated with team scoring",
    "strength": 0.08,
    "confidence": 0.65
  }
}
```

### Parlay Types

| Type | Description | Typical Legs |
|------|-------------|--------------|
| `primary` | Best overall edge parlay | 3-4 |
| `theme_stack` | Correlated theme (e.g., PP stack, rivalry offense) | 2-3 |
| `value_play` | High-value single or double | 1-2 |

### NHL Stat Types

| Code | Description | Market Key |
|------|-------------|------------|
| `points` | Points (G+A) | `player_points` |
| `goals` | Goals | `player_goals` |
| `assists` | Assists | `player_assists` |
| `shots_on_goal` | Shots on goal | `player_shots_on_goal` |
| `blocked_shots` | Blocked shots | `player_blocked_shots` |
| `saves` | Goalie saves | `player_total_saves` |

### Result Values

| Value | Description |
|-------|-------------|
| `WIN` | Leg/parlay hit |
| `LOSS` | Leg/parlay missed |
| `PUSH` | Exactly hit the line |
| `VOID` | Cancelled (DNP, etc.) |
| `null` | Not yet settled |

---

## Query Examples

### Python (Supabase Client)

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get today's parlays
response = supabase.table('nhl_sgp_parlays') \
    .select('*, nhl_sgp_legs(*)') \
    .eq('game_date', '2025-12-14') \
    .execute()

parlays = response.data

# Get primary parlays only
response = supabase.table('nhl_sgp_parlays') \
    .select('*, nhl_sgp_legs(*)') \
    .eq('parlay_type', 'primary') \
    .order('game_date', desc=True) \
    .execute()
```

### SQL Queries

```sql
-- Get parlays for a specific date with legs
SELECT
  p.*,
  json_agg(
    json_build_object(
      'leg_number', l.leg_number,
      'player_name', l.player_name,
      'stat_type', l.stat_type,
      'line', l.line,
      'direction', l.direction,
      'edge_pct', l.edge_pct,
      'primary_reason', l.primary_reason
    ) ORDER BY l.leg_number
  ) as legs
FROM nhl_sgp_parlays p
JOIN nhl_sgp_legs l ON p.id = l.parlay_id
WHERE p.game_date = '2025-12-14'
GROUP BY p.id
ORDER BY p.created_at DESC;

-- Get settled results
SELECT
  p.parlay_type,
  p.away_team || ' @ ' || p.home_team as matchup,
  s.legs_hit,
  s.total_legs,
  s.result,
  s.profit
FROM nhl_sgp_parlays p
JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
WHERE p.game_date >= '2025-12-01';

-- Performance by parlay type
SELECT
  parlay_type,
  COUNT(*) as total_parlays,
  SUM(CASE WHEN s.result = 'WIN' THEN 1 ELSE 0 END) as wins,
  ROUND(AVG(CASE WHEN s.result = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM nhl_sgp_parlays p
JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
GROUP BY parlay_type;
```

---

## Production Schedule

| Job | Day | Time (ET) | Description |
|-----|-----|-----------|-------------|
| `nhl_sgp_generate` | Daily | 9:00 AM | Generate parlays for today's games |
| `nhl_sgp_settle` | Daily | 9:00 AM | Settle yesterday's parlays |

### Pipeline Workflow

1. **Morning (9 AM ET)**:
   - Settle previous day's parlays from box scores
   - Fetch today's games from Odds API
   - Calculate edges for validated markets (points, SOG)
   - Generate 1 primary parlay per game
   - Optionally generate theme_stack if correlation detected
   - Write to database

2. **Settlement Logic**:
   - Fetch box scores from NHL API
   - Match player stats to legs
   - Mark each leg WIN/LOSS/PUSH/VOID
   - Calculate parlay result (WIN if all legs hit)
   - Calculate profit at $100 stake

---

## Orchestrator Integration

The NHL SGP pipeline integrates with `daily_orchestrator.py`:

```python
# In daily_orchestrator.py
from nhl_sgp_engine.scripts.run_sgp_pipeline import run_full_pipeline

def run_daily_tasks():
    # ... other tasks ...

    # NHL SGP Pipeline
    sgp_result = run_full_pipeline()
    log(f"NHL SGP: Generated {sgp_result['predictions']} parlays")
```

---

## Notes

1. **Edge Threshold**: Only legs with 10-15% edge are included (validated by backtest)
2. **Markets**: Currently limited to `player_points` and `player_shots_on_goal`
3. **Parlay Size**: Typically 3 legs for primary, 2-3 for theme_stack
4. **Combined Odds**: Calculated by multiplying decimal odds of each leg

---

*Document Version: 1.1*
*Last Updated: December 14, 2025*

---

## Changelog

### v1.1 (December 14, 2025)
- **Data Type Serialization**: UUIDs returned as strings, Decimals as floats for JSON compatibility
- **New DB Methods**: Added `get_settlement_for_parlay()` and `get_settlements_by_date()`
- **Duplicate Settlement Check**: Settlement script now checks for existing settlements before inserting
- **UUID Handling**: Settlement script properly converts string UUIDs back to UUID objects for DB queries
- **NULL Handling**: Fixed LEFT JOIN in `get_parlays_by_date()` to return empty array instead of `[null]`

### v1.0 (December 13, 2025)
- Initial release
