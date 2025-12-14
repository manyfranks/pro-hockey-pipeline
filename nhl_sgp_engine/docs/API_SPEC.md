# NHL SGP Engine API Specification

**Version:** 1.0 (POC)
**Last Updated:** December 13, 2025
**Status:** Proof of Concept - Not Production

---

## Overview

The NHL SGP (Same Game Parlay) Engine generates optimized player prop recommendations using a 6-signal analytical framework. Data is stored in Supabase and accessible via REST API or real-time subscriptions.

### Key Differences from NFL/NCAAF

| Aspect | NFL/NCAAF | NHL |
|--------|-----------|-----|
| Primary Stat | Pass/Rush/Rec Yards | Points |
| Line Values | 45.5, 55.5, etc. | 0.5, 1.5, 2.5 |
| Game Frequency | Weekly | Daily |
| Pipeline Context | ATTD Rankings | Scoreable Predictions |
| Validated Props | All stat types | **Points only** (see LEARNINGS.md) |

---

## Database Tables

### `nhl_sgp_parlays`

Parent table storing parlay recommendations.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `a1b2c3d4-...` |
| `parlay_type` | VARCHAR(50) | Parlay category | `primary`, `theme_stack`, `value_play` |
| `game_id` | VARCHAR(100) | Unique game identifier | `2025_NHL_TOR_MTL_20250115` |
| `game_date` | DATE | Game date | `2025-01-15` |
| `home_team` | VARCHAR(10) | Home team abbreviation | `MTL` |
| `away_team` | VARCHAR(10) | Away team abbreviation | `TOR` |
| `game_slot` | VARCHAR(20) | Time slot | `EVENING`, `AFTERNOON`, `MATINEE` |
| `total_legs` | INTEGER | Number of legs | `3` |
| `combined_odds` | INTEGER | American odds | `450` |
| `implied_probability` | DECIMAL(6,4) | Win probability | `0.1818` |
| `thesis` | TEXT | Narrative explanation | `Top-line forwards in high-total game...` |
| `season` | INTEGER | Season year | `2025` |
| `season_type` | VARCHAR(20) | Season phase | `regular`, `playoffs` |
| `created_at` | TIMESTAMP | Creation time | `2025-01-15T14:00:00Z` |
| `updated_at` | TIMESTAMP | Last update | `2025-01-15T14:00:00Z` |

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
| `team` | VARCHAR(10) | Team abbreviation | `TOR` |
| `position` | VARCHAR(10) | Position code | `C`, `LW`, `RW`, `D`, `G` |
| `stat_type` | VARCHAR(50) | Prop type | `points`, `goals`, `assists` |
| `line` | DECIMAL(6,1) | Prop line | `0.5`, `1.5` |
| `direction` | VARCHAR(10) | Over/under | `over`, `under` |
| `odds` | INTEGER | American odds | `-120`, `+100` |
| `edge_pct` | DECIMAL(5,2) | Projected edge | `7.5` |
| `confidence` | DECIMAL(3,2) | Confidence score | `0.78` |
| `model_probability` | DECIMAL(6,4) | Model win prob | `0.5850` |
| `market_probability` | DECIMAL(6,4) | Implied from odds | `0.5455` |
| `primary_reason` | TEXT | Main evidence | `L10 avg 1.2 PPG vs 0.5 line` |
| `supporting_reasons` | JSONB | Additional reasons | `["Top PP unit", "Weak goalie"]` |
| `risk_factors` | JSONB | Risk warnings | `["Back-to-back game"]` |
| `signals` | JSONB | Full signal breakdown | See Signal Object |
| `pipeline_score` | DECIMAL(6,2) | Pipeline final_score | `72.5` |
| `pipeline_confidence` | VARCHAR(20) | Pipeline confidence | `very_high` |
| `pipeline_rank` | INTEGER | Daily pipeline rank | `5` |
| `actual_value` | DECIMAL(6,1) | Post-game actual | `2.0` |
| `result` | VARCHAR(10) | Settlement result | `WIN`, `LOSS`, `PUSH`, `VOID` |
| `created_at` | TIMESTAMP | Creation time | `2025-01-15T14:00:00Z` |

**Foreign Key:** `parlay_id` references `nhl_sgp_parlays(id)`

---

### `nhl_sgp_settlements`

Settlement records for completed parlays.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `c3d4e5f6-...` |
| `parlay_id` | UUID | FK to parlays | `a1b2c3d4-...` |
| `legs_hit` | INTEGER | Legs that hit | `2` |
| `total_legs` | INTEGER | Total scoreable legs | `3` |
| `result` | VARCHAR(10) | Parlay result | `WIN`, `LOSS`, `VOID` |
| `profit` | DECIMAL(10,2) | Profit at $100 stake | `450.00` |
| `settled_at` | TIMESTAMP | Settlement time | `2025-01-16T08:00:00Z` |
| `notes` | TEXT | Settlement notes | `Settled via pipeline` |

---

### `nhl_sgp_historical_odds`

Historical odds cache for backtesting.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | INTEGER | Primary key (auto) | `12345` |
| `event_id` | VARCHAR(100) | Odds API event ID | `abc123def456` |
| `game_date` | DATE | Game date | `2025-12-06` |
| `home_team` | VARCHAR(10) | Home team | `TOR` |
| `away_team` | VARCHAR(10) | Away team | `MTL` |
| `player_name` | VARCHAR(100) | Player name | `Auston Matthews` |
| `player_id` | INTEGER | NHL player ID | `8479318` |
| `stat_type` | VARCHAR(50) | Stat type | `points`, `goals` |
| `market_key` | VARCHAR(50) | Odds API market key | `player_points` |
| `line` | DECIMAL(6,2) | Prop line | `0.5`, `1.5` |
| `over_price` | INTEGER | Over odds | `-120` |
| `under_price` | INTEGER | Under odds | `+100` |
| `bookmaker` | VARCHAR(50) | Sportsbook | `draftkings` |
| `snapshot_time` | TIMESTAMP | When odds captured | `2025-12-06T12:00:00Z` |
| `actual_value` | DECIMAL(6,2) | Post-game actual | `1.0` |
| `over_hit` | BOOLEAN | Did over hit? | `true` |
| `settled` | BOOLEAN | Is settled? | `true` |
| `created_at` | TIMESTAMP | Creation time | `2025-12-06T12:00:00Z` |

**Unique Constraint:** `(event_id, player_name, stat_type, bookmaker, line)`

---

## Signal Object Schema

The `signals` JSONB column contains the full signal breakdown:

```json
{
  "line_value": {
    "evidence": "Season avg 0.85 PPG is 70% ABOVE line 0.5 (strong edge)",
    "strength": 0.7,
    "confidence": 0.85
  },
  "trend": {
    "evidence": "L10 avg 1.1 PPG vs season 0.85 (UP 29.4%)",
    "strength": 0.29,
    "confidence": 0.78
  },
  "usage": {
    "evidence": "TOI STABLE: 18.5 min L5 vs 18.2 season",
    "strength": 0.02,
    "confidence": 0.90
  },
  "matchup": {
    "evidence": "Facing weak goalie (0.898 SV%)",
    "strength": 0.25,
    "confidence": 0.75
  },
  "environment": {
    "evidence": "Home game, not B2B",
    "strength": 0.1,
    "confidence": 0.80
  },
  "correlation": {
    "evidence": "High total (6.5) correlates +20% with points",
    "strength": 0.12,
    "confidence": 0.65
  }
}
```

**Signal Interpretation:**
- `strength`: -1.0 to +1.0 (negative = UNDER, positive = OVER)
- `confidence`: 0.0 to 1.0 (higher = more reliable signal)

---

## Query Examples

### Get Today's Parlays with Legs

```sql
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
WHERE p.game_date = CURRENT_DATE
GROUP BY p.id
ORDER BY p.created_at DESC;
```

### Get High-Edge Points Props

```sql
SELECT *
FROM nhl_sgp_historical_odds
WHERE stat_type = 'points'
  AND game_date >= '2025-12-01'
  AND settled = true
ORDER BY game_date DESC;
```

### Backtest Performance by Stat Type

```sql
SELECT
  stat_type,
  COUNT(*) as total_props,
  SUM(CASE WHEN over_hit THEN 1 ELSE 0 END) as over_hits,
  ROUND(AVG(CASE WHEN over_hit THEN 1.0 ELSE 0.0 END) * 100, 1) as hit_rate_pct
FROM nhl_sgp_historical_odds
WHERE settled = true
GROUP BY stat_type
ORDER BY hit_rate_pct DESC;
```

### Get Pipeline-Enriched Props

```sql
SELECT
  h.player_name,
  h.stat_type,
  h.line,
  h.over_price,
  h.under_price,
  p.final_score as pipeline_score,
  p.rank as pipeline_rank,
  p.is_scoreable,
  h.actual_value,
  h.over_hit
FROM nhl_sgp_historical_odds h
JOIN nhl_daily_predictions p
  ON h.player_name ILIKE '%' || p.player_name || '%'
  AND h.game_date = p.analysis_date
WHERE h.settled = true
  AND p.is_scoreable = true
ORDER BY p.rank ASC;
```

---

## REST API (Supabase)

### Get Parlays by Date

```http
GET /nhl_sgp_parlays?game_date=eq.2025-01-15&select=*,nhl_sgp_legs(*)
```

### Get Primary Parlays

```http
GET /nhl_sgp_parlays?parlay_type=eq.primary&select=*,nhl_sgp_legs(*)&order=game_date.desc
```

### Get Settled Results

```http
GET /nhl_sgp_parlays?select=*,nhl_sgp_legs(*),nhl_sgp_settlements(*)
  &nhl_sgp_settlements.result=not.is.null
```

---

## Stat Types

| Code | Description | Supported | Notes |
|------|-------------|-----------|-------|
| `points` | Points (G+A) | **Yes** | Primary - validated at 50% hit rate |
| `goals` | Goals | No | 7.4% hit rate - market correctly priced |
| `assists` | Assists | TBD | Not yet tested |
| `shots_on_goal` | SOG | TBD | Not yet tested |
| `saves` | Goalie saves | TBD | Not yet tested |

---

## Market Keys (Odds API)

| Market Key | Stat Type | Status |
|------------|-----------|--------|
| `player_points` | points | Active |
| `player_goals` | goals | **Disabled** |
| `player_assists` | assists | Pending |
| `player_shots_on_goal` | shots_on_goal | Pending |
| `player_total_saves` | saves | Pending |

---

*Document Version: 1.0*
*Last Updated: December 13, 2025*
