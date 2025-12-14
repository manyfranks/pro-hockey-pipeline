# SGP Engine API Specification

## Overview

This document provides the API specification for integrating with the SGP (Same Game Parlay) engine. Use this as the source of truth for frontend/backend development.

---

## Database Schema (Supabase)

### Table: `nfl_sgp_parlays`

Parent record for each parlay recommendation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_type` | VARCHAR(50) | `'primary'`, `'theme_stack'`, `'value_play'` |
| `game_id` | VARCHAR(100) | e.g., `'2025_15_MIN_DAL'` |
| `game_date` | DATE | Game date |
| `home_team` | VARCHAR(10) | Team abbreviation |
| `away_team` | VARCHAR(10) | Team abbreviation |
| `game_slot` | VARCHAR(10) | `'TNF'`, `'SNF'`, `'MNF'`, `'EARLY'`, `'LATE'` |
| `total_legs` | INTEGER | Number of legs in parlay |
| `combined_odds` | INTEGER | American odds (e.g., +450) |
| `implied_probability` | DECIMAL | Combined probability |
| `thesis` | TEXT | Narrative explanation |
| `season` | INTEGER | NFL season year |
| `week` | INTEGER | Week number |
| `created_at` | TIMESTAMPTZ | When generated |

**Unique Constraint:** `(season, week, parlay_type, game_id)`

### Table: `nfl_sgp_legs`

Individual legs within each parlay.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_id` | UUID | FK to `nfl_sgp_parlays.id` |
| `leg_number` | INTEGER | Order within parlay (1, 2, 3...) |
| `player_name` | VARCHAR(100) | Player display name |
| `team` | VARCHAR(10) | Team abbreviation |
| `position` | VARCHAR(10) | QB, RB, WR, TE |
| `stat_type` | VARCHAR(50) | `'pass_yds'`, `'rush_yds'`, `'rec_yds'`, `'receptions'`, etc. |
| `line` | DECIMAL | Prop line (e.g., 55.5) |
| `direction` | VARCHAR(10) | `'over'` or `'under'` |
| `odds` | INTEGER | American odds (e.g., -110) |
| `edge_pct` | DECIMAL | Projected edge percentage |
| `confidence` | DECIMAL | 0.0 to 1.0 |
| `primary_reason` | TEXT | Main evidence statement |
| `supporting_reasons` | JSONB | Array of strings |
| `risk_factors` | JSONB | Array of strings |
| `signals` | JSONB | Signal breakdown (see below) |
| `actual_value` | DECIMAL | Filled after settlement |
| `result` | VARCHAR(10) | `'WIN'`, `'LOSS'`, `'PUSH'`, `'VOID'` |
| `created_at` | TIMESTAMPTZ | When generated |

### Table: `nfl_sgp_settlements`

Settlement records for tracking parlay outcomes.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_id` | UUID | FK to `nfl_sgp_parlays.id` |
| `season` | INTEGER | NFL season year |
| `week` | INTEGER | Week number |
| `legs_hit` | INTEGER | Number of legs that hit |
| `total_legs` | INTEGER | Total legs (excluding VOIDs) |
| `parlay_result` | VARCHAR(10) | `'WIN'`, `'LOSS'`, `'VOID'` |
| `notes` | TEXT | Settlement notes |
| `settled_at` | TIMESTAMPTZ | When settled |

---

## Signal Schema (JSONB)

The `signals` field in `nfl_sgp_legs` contains:

```json
{
  "trend": {
    "evidence": "Averaging 2.7 receptions L3 vs 4.9 season (-45.8%) - TRENDING DOWN",
    "strength": -0.92,
    "confidence": 0.78
  },
  "usage": {
    "evidence": "Targets DECREASING: 5.3/gm L3 vs 8.4 season (-36%)",
    "strength": -0.73,
    "confidence": 0.89
  },
  "matchup": {
    "evidence": "DAL allows 10th receiving yards to WRs (0.0/gm)",
    "strength": -0.21,
    "confidence": 0.90
  },
  "environment": {
    "evidence": "Dome game",
    "strength": 0.03,
    "confidence": 0.90
  },
  "correlation": {
    "evidence": "High total (48.5) correlates +35% with receptions",
    "strength": 0.05,
    "confidence": 0.65
  }
}
```

**Signal Interpretation:**
- `strength`: -1.0 to +1.0 (negative = UNDER, positive = OVER)
- `confidence`: 0.0 to 1.0 (higher = more reliable signal)

---

## Common Queries

### Get parlays for a specific week

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
FROM nfl_sgp_parlays p
JOIN nfl_sgp_legs l ON p.id = l.parlay_id
WHERE p.season = 2025 AND p.week = 15
GROUP BY p.id
ORDER BY p.created_at DESC;
```

### Get parlays by game slot

```sql
SELECT * FROM nfl_sgp_parlays
WHERE season = 2025 AND week = 15 AND game_slot = 'SNF';
```

### Get settled results

```sql
SELECT
  p.parlay_type,
  p.away_team || ' @ ' || p.home_team as matchup,
  s.legs_hit,
  s.total_legs,
  s.parlay_result
FROM nfl_sgp_parlays p
JOIN nfl_sgp_settlements s ON p.id = s.parlay_id
WHERE p.season = 2025 AND p.week = 15;
```

### Performance by parlay type

```sql
SELECT * FROM v_sgp_weekly_summary
WHERE season = 2025
ORDER BY week DESC;
```

---

## REST API Endpoints (Proposed)

### GET `/api/sgp/parlays`

Query parameters:
- `season` (required): NFL season year
- `week` (required): Week number
- `slot` (optional): `TNF`, `SNF`, `MNF`
- `type` (optional): `primary`, `theme_stack`, `value_play`

Response:
```json
{
  "parlays": [
    {
      "id": "57ec0acf-42a5-4b69-82d7-47c8ec723647",
      "parlay_type": "primary",
      "game": {
        "id": "2025_15_MIN_DAL",
        "away_team": "MIN",
        "home_team": "DAL",
        "date": "2025-12-15",
        "slot": "SNF"
      },
      "legs": [
        {
          "player": "Justin Jefferson",
          "team": "MIN",
          "prop": "receptions UNDER 5.5",
          "edge_pct": 7.0,
          "reason": "Averaging 2.7 receptions L3 vs 4.9 season (-45.8%)"
        }
      ],
      "thesis": "High total (48.5) suggests offensive-friendly game script...",
      "created_at": "2025-12-13T04:53:33Z"
    }
  ]
}
```

### GET `/api/sgp/parlays/:id`

Returns single parlay with full leg details including signals.

### GET `/api/sgp/performance`

Query parameters:
- `season` (required)
- `weeks` (optional): Range like `1-15`

Response:
```json
{
  "summary": {
    "total_parlays": 28,
    "parlays_won": 4,
    "parlay_win_rate": 14.3,
    "total_legs": 112,
    "legs_hit": 58,
    "leg_hit_rate": 51.8
  },
  "by_type": {
    "primary": { "count": 14, "win_rate": 14.3 },
    "theme_stack": { "count": 10, "win_rate": 20.0 },
    "value_play": { "count": 4, "win_rate": 0.0 }
  }
}
```

---

## Production Schedule

| Job | Day | Time (UTC) | Description |
|-----|-----|------------|-------------|
| `sgp_tnf` | Thursday | 19:00 | Generate TNF parlay |
| `sgp_snf_mnf` | Sunday | 19:00 | Generate SNF + MNF parlays |
| `sgp_settlement` | Tuesday | 15:00 | Settle previous week's parlays |

---

## Notes for Frontend

1. **Parlays update**: When `run_primetime.py` executes, existing parlays for the same (season, week, parlay_type, game_id) are **updated** with fresh data (upsert behavior).

2. **Settlement timing**: Parlays are settled on Tuesday. Before then, `result` fields will be NULL.

3. **Game slots**:
   - `TNF`: Thursday Night Football
   - `SNF`: Sunday Night Football
   - `MNF`: Monday Night Football
   - `EARLY`/`LATE`: Future support for Sunday slate

4. **Stat types**:
   - `pass_yds`, `pass_tds`, `completions`, `pass_attempts`
   - `rush_yds`, `rush_attempts`, `rush_tds`
   - `rec_yds`, `receptions`, `rec_tds`

---

*Document Version: 1.0*
*Last Updated: December 2025*
