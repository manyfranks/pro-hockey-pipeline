# NHL SGP Engine Data Inventory

**Version:** 1.0 (POC)
**Last Updated:** December 13, 2025

---

## Overview

This document catalogs all data sources available to the NHL SGP Engine, their refresh rates, and how they map to the signal framework.

---

## Dual-Path Architecture

The NHL SGP Engine uses two data paths based on the validated "Strategic Blend" decision:

### Path A: Points/Assists (VALIDATED - 62.5% hit rate)

| Data Source | Purpose | Required? |
|-------------|---------|-----------|
| Odds API | Prop lines and prices | Yes |
| Pipeline (`nhl_daily_predictions`) | Player context, scoreable filter, rank | **Yes - THIS IS OUR EDGE** |

**Key insight:** The pipeline provides derived intelligence (line deployment, PP units, scoreable composite) that drives our 61.4% hit rate for scoreable players.

### Path B: SOG/Saves/Blocks (EXPLORATORY - unvalidated)

| Data Source | Purpose | Required? |
|-------------|---------|-----------|
| Odds API | Prop lines and prices | Yes |
| NHL API Direct | On-demand stat queries | Yes |
| Pipeline | Optional enrichment if available | No |

**Key insight:** For prop types the pipeline doesn't track, we query NHL API directly. Validate signal BEFORE investing in pipeline support.

### Data Source by Prop Type

| Prop Type | Path | Primary Data | Pipeline Context |
|-----------|------|--------------|------------------|
| Points | A | Pipeline | **Required** (is_scoreable, rank) |
| Assists | A | Pipeline | **Required** |
| Goals | A | Pipeline | Required (but 7.4% hit rate - avoid) |
| SOG | B | NHL API Direct | Optional |
| Saves | B | NHL API Direct | Optional |
| Blocked Shots | B | NHL API Direct | Optional |

---

## Data Sources

### 1. NHL Pipeline Database (`nhl_daily_predictions`)

**Source:** Main NHL points prediction pipeline
**Refresh:** Daily (6 AM UTC)
**Coverage:** All "scoreable" players for scheduled games

| Field | Type | Description | Signal Usage |
|-------|------|-------------|--------------|
| `player_id` | INT | NHL player ID | Player identification |
| `player_name` | VARCHAR | Full name | Player identification |
| `team` | VARCHAR | Team abbreviation | Context |
| `position` | VARCHAR | C, LW, RW, D | Context |
| `opponent` | VARCHAR | Opponent team | Matchup signal |
| `is_home` | BOOL | Home/away | Environment signal |
| `game_id` | VARCHAR | NHL game ID | Settlement matching |
| `analysis_date` | DATE | Prediction date | Temporal key |
| `final_score` | DECIMAL | 0-100 composite | Pipeline confidence |
| `rank` | INT | Daily ranking | Pipeline confidence |
| `confidence` | VARCHAR | very_high/high/medium/low | Pipeline confidence |
| `is_scoreable` | BOOL | Meets scoring criteria | Primary filter |
| `recent_form_score` | DECIMAL | Component score | Trend signal |
| `line_opportunity_score` | DECIMAL | Component score | Usage signal |
| `goalie_weakness_score` | DECIMAL | Component score | Matchup signal |
| `matchup_score` | DECIMAL | Component score | Matchup signal |
| `situational_score` | DECIMAL | Component score | Environment signal |
| `line_number` | INT | Even-strength line (1-4) | Usage signal |
| `pp_unit` | INT | Power play unit (1-2, null) | Usage signal |
| `avg_toi_minutes` | DECIMAL | Average TOI | Usage signal |
| `recent_ppg` | DECIMAL | L10 PPG | Trend signal |
| `recent_games` | INT | Games in recent window | Trend signal |
| `recent_points` | INT | Points in window | Trend signal |
| `point_streak` | INT | Current point streak | Trend signal |
| `opposing_goalie_id` | INT | Goalie ID | Matchup signal |
| `opposing_goalie_name` | VARCHAR | Goalie name | Matchup signal |
| `opposing_goalie_sv_pct` | DECIMAL | Save percentage | Matchup signal |
| `opposing_goalie_gaa` | DECIMAL | Goals against avg | Matchup signal |
| `goalie_confirmed` | BOOL | Starter confirmed | Matchup confidence |
| `is_b2b` | BOOL | Back-to-back game | Environment signal |
| `season_games` | INT | Games played | Line value signal |
| `season_goals` | INT | Total goals | Line value signal |
| `season_assists` | INT | Total assists | Line value signal |
| `season_points` | INT | Total points | Line value signal |
| `point_outcome` | VARCHAR | Settlement result | Backtest validation |
| `actual_points` | INT | Post-game points | Backtest validation |
| `actual_goals` | INT | Post-game goals | Backtest validation |
| `actual_assists` | INT | Post-game assists | Backtest validation |

**Access Pattern:**
```python
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter

pipeline = PipelineAdapter()
predictions = pipeline.get_predictions_for_date(game_date)
context = pipeline.get_prediction_context(player_name, game_date)
actual = pipeline.get_actual_outcome(player_name, 'points', game_date)
```

---

### 2. The Odds API (Historical)

**Source:** The Odds API (https://the-odds-api.com)
**Refresh:** On-demand fetch (API budget: 3k/month allocated)
**Coverage:** Historical player props from May 2023+

| Endpoint | Cost | Data |
|----------|------|------|
| `GET /v4/historical/sports/{sport}/events` | 1 call | List of events for date |
| `GET /v4/historical/sports/{sport}/events/{eventId}/odds` | 10 calls/market/region | Player prop odds |

**Markets Available:**

| Market Key | Stat Type | Backtest Status |
|------------|-----------|-----------------|
| `player_points` | points | **Active** - validated |
| `player_goals` | goals | **Disabled** - 7.4% hit rate |
| `player_assists` | assists | Pending validation |
| `player_shots_on_goal` | shots_on_goal | Pending |
| `player_blocked_shots` | blocked_shots | Pending |
| `player_power_play_points` | pp_points | Pending |
| `player_total_saves` | saves | Pending |
| `player_goal_scorer_anytime` | anytime_goal | Pending |

**Supported Bookmakers:**
- DraftKings (primary)
- FanDuel
- BetMGM
- Caesars
- PointsBet
- Bovada

**Access Pattern:**
```python
from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient

client = OddsAPIClient()
events = client.get_historical_events('2025-12-06')
odds = client.get_historical_event_odds(
    event_id='abc123',
    date_str='2025-12-06',
    markets=['player_points']
)
props = client.parse_player_props(odds)
```

**Budget Tracking:**
```python
status = client.test_connection()
print(f"Remaining: {status['requests_remaining']}")
print(f"Used: {status['requests_used']}")
```

---

### 3. NHL Official API (via Pipeline)

**Source:** NHL Stats API (api-web.nhle.com)
**Refresh:** Real-time during games, daily for historical
**Access:** Indirect via `nhl_daily_predictions` table

Data points sourced from NHL API:
- Player season statistics
- Recent game logs (L10)
- Line combinations
- Power play units
- Game schedules
- Goalie assignments

**Note:** The SGP engine does not directly call the NHL API. All NHL data is pre-processed by the main pipeline and stored in `nhl_daily_predictions`.

---

### 4. DailyFaceoff (via Pipeline)

**Source:** DailyFaceoff.com scraping
**Refresh:** Daily (during pipeline run)
**Access:** Indirect via `nhl_daily_predictions` table

Data points sourced from DailyFaceoff:
- Line combinations (`line_number`)
- Power play units (`pp_unit`)
- Goalie confirmations (`goalie_confirmed`)
- Injury updates

---

## Data Flow

```
┌─────────────────────┐     ┌─────────────────────┐
│   NHL Official API  │     │   DailyFaceoff      │
└─────────┬───────────┘     └─────────┬───────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────────┐
│        NHL Points Prediction Pipeline           │
│        (nhl_daily_predictions table)            │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│            Pipeline Adapter                     │
│   - Enriches prop context                       │
│   - Provides settlement data                    │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│           NHL SGP Engine                        │
│   ┌─────────────┐  ┌─────────────────┐          │
│   │ Odds API    │  │ Signal Framework │          │
│   │ Client      │──│ (6 signals)     │          │
│   └─────────────┘  └─────────────────┘          │
│           │                │                    │
│           ▼                ▼                    │
│   ┌─────────────────────────────────┐          │
│   │       Edge Calculator           │          │
│   │ model_prob - market_prob = edge │          │
│   └─────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
```

---

## Signal-to-Data Mapping

| Signal | Weight | Primary Data Source | Fields Used |
|--------|--------|---------------------|-------------|
| Line Value | 35% | Pipeline (`nhl_daily_predictions`) | `season_games`, `season_points`, `season_goals`, `season_assists` |
| Trend | 15% | Pipeline | `recent_ppg`, `recent_games`, `point_streak`, `recent_form_score` |
| Usage | 10% | Pipeline | `line_number`, `pp_unit`, `avg_toi_minutes`, `line_opportunity_score` |
| Matchup | 15% | Pipeline | `opposing_goalie_sv_pct`, `opposing_goalie_gaa`, `goalie_weakness_score` |
| Environment | 15% | Pipeline | `is_home`, `is_b2b`, `situational_score` |
| Correlation | 10% | Odds API (game lines) | `game_total`, `spread` |

---

## Data Gaps

### Currently Missing

1. **Game totals/spreads**: Not stored in pipeline; must fetch from Odds API per-game
2. **Defensive metrics**: No team-level defensive stats against specific positions
3. **Shot-based stats**: No shot attempts, shot quality, or expected goals
4. **Special teams %**: No PP% or PK% for teams
5. **Head-to-head history**: No player vs specific goalie history

### Impact on Signals

| Missing Data | Affected Signal | Mitigation |
|--------------|-----------------|------------|
| Game totals | Correlation | Fetch from Odds API (costs API calls) |
| Team defense | Matchup | Use goalie stats as proxy |
| Shot metrics | Line Value (goals) | **Don't use goals props** |
| Special teams | Usage | Use `pp_unit` as binary indicator |

---

## Caching Strategy

### Local Cache

```python
from nhl_sgp_engine.config.settings import CACHE_DIR, ODDS_CACHE_DIR

# Odds API responses cached for 6 hours
# Historical odds stored permanently in nhl_sgp_historical_odds
```

### Database Cache

| Table | Purpose | Retention |
|-------|---------|-----------|
| `nhl_sgp_historical_odds` | Backtest data | Permanent |
| `nhl_daily_predictions` | Pipeline context | 90 days |

---

## API Budget Management

**Monthly Allocation:** 20,000 calls (shared across all pipelines)
**NHL SGP Budget:** 3,000 calls

**Cost Breakdown:**
- Historical events list: 1 call
- Historical odds (per event): 10 calls x markets x regions
- Current: 2 markets x 1 region = 20 calls/game

**Capacity:** 3000 / 20 = **150 games** for backfill

**Current Usage (as of Dec 13, 2025):**
- Fetched: 12 games (Dec 6, 9, 11)
- Props loaded: 1,462
- Remaining budget: ~2,760 calls

---

## Quality Considerations

### Pipeline Data Quality

| Issue | Frequency | Impact | Mitigation |
|-------|-----------|--------|------------|
| Name mismatches | ~5% | Missed enrichment | Fuzzy matching (ILIKE) |
| Missing goalies | ~10% | Low matchup confidence | Reduce signal weight |
| Stale line combos | ~15% | Wrong usage signal | DailyFaceoff refresh |
| Decimal types | 100% | Type errors | Explicit `float()` conversion |

### Odds API Data Quality

| Issue | Frequency | Impact | Mitigation |
|-------|-----------|--------|------------|
| Missing props | ~20% | Reduced sample | Accept lower coverage |
| Price staleness | N/A (historical) | None | Use snapshot_time |
| Bookmaker gaps | ~30% | Missing best price | Use DraftKings as default |

---

*Document Version: 1.0*
*Last Updated: December 13, 2025*
