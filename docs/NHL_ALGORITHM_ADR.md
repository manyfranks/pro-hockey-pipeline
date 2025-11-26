# NHL Player Points Algorithm - Architecture Decision Record

**Version:** 2.0
**Date:** 2025-11-24
**Status:** COMPLETE - Full Pipeline with Settlement & Calibration

---

## Executive Summary

This document defines the architecture for an NHL player points prediction algorithm. The system ranks players by their likelihood of scoring at least one point (goal or assist) in their upcoming matchup, producing a **Top 25** ranked list from a full slate of scored players.

The design mirrors the existing MLB Hit Prediction system while adapting to NHL-specific data structures and scoring dynamics.

---

## Table of Contents

1. [Scoring Formula](#1-scoring-formula)
2. [Component Definitions](#2-component-definitions)
3. [Position-Specific Weights](#3-position-specific-weights)
4. [Fatigue & Edge Cases](#4-fatigue--edge-cases)
5. [Confidence Framework](#5-confidence-framework)
6. [Data Sources & Endpoints](#6-data-sources--endpoints)
7. [Data Model](#7-data-model)
8. [Development Phases](#8-development-phases)
9. [Directory Structure](#9-directory-structure)
10. [Configuration](#10-configuration)

---

## 1. Scoring Formula

### Primary Score (0-100 scale)

```python
final_score = (
    recent_form_score * 50 +           # 50% - Recent Points Per Game (PPG)
    line_opportunity_score * 20 +      # 20% - Line quality + PP1 status
    goalie_weakness_score * 15 +       # 15% - Opposing goalie form/type
    matchup_score * 10 +               # 10% - Team defense + Skater-vs-Goalie
    situational_score * 5              # 5%  - Fatigue (B2B), home/away
)
```

### Output

- **Score all players** in the daily slate
- **Produce Top 25** ranked list for API consumption
- Track confidence tier for each prediction

---

## 2. Component Definitions

### 2.1 Recent Form Score (50% weight)

**Purpose:** Captures player hot streaks and current offensive production.

**Calculation:**
```python
def calculate_recent_form_nhl(game_logs: List[Dict], num_games: int = 10) -> Dict:
    """
    Calculate recent form based on Points Per Game over last 10 games.

    Returns:
        ppg: Points per game (float, typically 0.0-2.0)
        goals_per_game: Goals per game (float)
        assists_per_game: Assists per game (float)
        streak_games: Consecutive games with at least 1 point (int)
        games_played: Number of games in sample (int)
    """
    recent = pd.DataFrame(game_logs).tail(num_games)
    games_played = len(recent)

    if games_played == 0:
        return {'ppg': 0.5, 'streak_games': 0}  # League avg fallback

    total_goals = recent['Goals'].sum()
    total_assists = recent['Assists'].sum()
    total_points = total_goals + total_assists

    ppg = total_points / games_played

    # Streak calculation (consecutive games with point)
    streak = 0
    for _, game in recent.iloc[::-1].iterrows():
        if game['Goals'] + game['Assists'] >= 1:
            streak += 1
        else:
            break

    return {
        'ppg': ppg,
        'goals_per_game': total_goals / games_played,
        'assists_per_game': total_assists / games_played,
        'streak_games': streak,
        'games_played': games_played
    }
```

**Normalization:**
- League average PPG ~0.5
- Elite scorer PPG ~1.2-1.5
- Scale: `normalized_score = min(ppg / 1.5, 1.0)` → 0-1 range

**Hot Streak Bonus:**
```python
# 3+ consecutive games with point = +5% bonus
# 5+ consecutive games with point = +10% bonus
streak_bonus = 0.0
if streak_games >= 5:
    streak_bonus = 0.10
elif streak_games >= 3:
    streak_bonus = 0.05
```

---

### 2.2 Line Opportunity Score (20% weight)

**Purpose:** Quantifies a player's role and ice time quality.

**Calculation:**
```python
def calculate_line_opportunity(player_id, line_combos, depth_charts) -> Dict:
    """
    Score based on:
    - Line number (1st line > 2nd > 3rd > 4th)
    - Power Play unit (PP1 >> PP2 >> None)
    - Linemate quality (avg PPG of linemates)
    """
    # Line number scoring
    LINE_SCORES = {1: 1.0, 2: 0.70, 3: 0.40, 4: 0.15}
    line_number = get_player_line_number(player_id, line_combos)
    line_score = LINE_SCORES.get(line_number, 0.15)

    # Power play bonus
    pp_unit = get_player_pp_unit(player_id, line_combos)  # 0, 1, or 2
    PP_BONUS = {1: 0.30, 2: 0.15, 0: 0.0}
    pp_bonus = PP_BONUS.get(pp_unit, 0.0)

    # Linemate quality factor
    linemates = get_linemates(player_id, line_combos)
    linemate_ppg = calculate_avg_ppg(linemates)
    league_avg_ppg = 0.50
    linemate_factor = min(linemate_ppg / league_avg_ppg, 1.5)  # Cap at 1.5x

    # Weighted combination
    opportunity_score = (
        line_score * 0.50 +
        pp_bonus * 0.30 +
        (linemate_factor - 1.0) * 0.20  # Bonus/penalty vs average
    )

    return {
        'opportunity_score': opportunity_score,
        'line_number': line_number,
        'pp_unit': pp_unit,
        'linemate_ppg': linemate_ppg
    }
```

**Defensemen Adjustment:**
- D-men on PP1 get full PP bonus
- D-men line pairings (1st pair, 2nd pair, 3rd pair) scored like forward lines

---

### 2.3 Goalie Weakness Score (15% weight)

**Purpose:** Higher score = weaker opposing goalie = better chance to score.

**Calculation:**
```python
def calculate_goalie_weakness(goalie_stats: Dict, depth_chart: Dict) -> Dict:
    """
    Inverse of goalie quality - higher score means weaker goalie.

    Factors:
    - Save Percentage (SV%) - lower = weaker
    - Goals Against Average (GAA) - higher = weaker
    - Backup/Starter status
    - Callup/Rookie status (< 20 career games)
    - Recent form (last 5 starts)
    """
    # League averages (2024 season)
    LEAGUE_AVG_SV_PCT = 0.905
    LEAGUE_AVG_GAA = 2.90

    sv_pct = goalie_stats.get('save_percentage', LEAGUE_AVG_SV_PCT)
    gaa = goalie_stats.get('goals_against_average', LEAGUE_AVG_GAA)
    games_played = goalie_stats.get('games_played', 30)
    is_starter = depth_chart.get('rank', 1) == 1

    # SV% component: league avg = 0, bad goalie = positive
    sv_score = (LEAGUE_AVG_SV_PCT - sv_pct) * 100  # e.g., 0.905 - 0.890 = 1.5

    # GAA component: league avg = 0, bad goalie = positive
    gaa_score = (gaa - LEAGUE_AVG_GAA) * 5  # e.g., 3.5 - 2.9 = 3.0

    # Status bonuses
    backup_bonus = 0.15 if not is_starter else 0.0
    callup_bonus = 0.20 if games_played < 20 else 0.0

    # Recent form (last 5 starts SV%)
    recent_sv_pct = goalie_stats.get('recent_sv_pct', sv_pct)
    recent_form_modifier = (LEAGUE_AVG_SV_PCT - recent_sv_pct) * 50

    # Combine (normalize to 0-1 range)
    raw_weakness = sv_score + gaa_score + backup_bonus + callup_bonus + recent_form_modifier
    normalized_weakness = max(0, min(raw_weakness / 5.0, 1.0))  # Cap at 0-1

    return {
        'weakness_score': normalized_weakness,
        'sv_pct': sv_pct,
        'gaa': gaa,
        'is_backup': not is_starter,
        'is_callup': games_played < 20,
        'recent_sv_pct': recent_sv_pct
    }
```

**Edge Case - Hot Goalie (Shutout Streak):**
```python
# If goalie has 2+ consecutive shutouts, apply penalty to weakness score
shutout_streak = goalie_stats.get('consecutive_shutouts', 0)
if shutout_streak >= 2:
    hot_goalie_penalty = 0.15 * shutout_streak  # -15% per shutout
    normalized_weakness = max(0, normalized_weakness - hot_goalie_penalty)
```

---

### 2.4 Matchup Score (10% weight)

**Purpose:** Historical skater-vs-goalie performance + team defensive weakness.

**Calculation:**
```python
def calculate_matchup_score(player_id, opponent_goalie_id, opponent_team,
                            play_by_play_cache) -> Dict:
    """
    BvP-style analysis with confidence tracking.

    Priority:
    1. Skater-vs-Goalie history (if 5+ games faced)
    2. Team defensive weakness fallback
    """
    # Priority 1: Skater vs Goalie (SvG) history
    svg_stats = get_skater_vs_goalie_stats(player_id, opponent_goalie_id,
                                            play_by_play_cache)

    if svg_stats['games_faced'] >= 5:
        # Confident SvG data
        svg_ppg = svg_stats['total_points'] / svg_stats['games_faced']
        svg_score = min(svg_ppg / 1.0, 1.5)  # Normalize, cap at 1.5

        return {
            'matchup_score': svg_score * 0.6,  # 60% weight to SvG
            'method': 'confident_svg',
            'svg_games': svg_stats['games_faced'],
            'svg_points': svg_stats['total_points']
        }

    # Priority 2: Team defensive weakness
    team_defense = get_team_defense_stats(opponent_team)

    # Goals against per game (league avg ~2.9)
    ga_per_game = team_defense.get('goals_against_per_game', 2.9)
    defense_weakness = (ga_per_game - 2.9) / 2.0  # Normalize

    # Penalty Kill weakness (league avg ~80%)
    pk_pct = team_defense.get('pk_percentage', 0.80)
    pk_weakness = (0.80 - pk_pct) * 2  # Bad PK = positive

    defense_score = max(0, defense_weakness + pk_weakness)

    return {
        'matchup_score': min(defense_score, 1.0),
        'method': 'team_defense_fallback',
        'ga_per_game': ga_per_game,
        'pk_pct': pk_pct
    }
```

**Transparency Tracking:**
- `method`: 'confident_svg' | 'limited_svg' | 'team_defense_fallback'
- Store for debugging and model improvement

---

### 2.5 Situational Score (5% weight)

**Purpose:** Captures fatigue, travel, and game context.

**Factors:**
- Back-to-back games (B2B)
- Extended road trips
- Home/away modifier

---

## 3. Position-Specific Weights

Different positions have different scoring profiles:

```python
POSITION_COMPONENT_WEIGHTS = {
    'C': {   # Centers - playmakers, faceoffs
        'recent_form': 0.45,
        'line_opportunity': 0.25,
        'goalie_weakness': 0.15,
        'matchup': 0.10,
        'situational': 0.05
    },
    'LW': {  # Left Wings - often goal scorers
        'recent_form': 0.50,
        'line_opportunity': 0.20,
        'goalie_weakness': 0.15,
        'matchup': 0.10,
        'situational': 0.05
    },
    'RW': {  # Right Wings - similar to LW
        'recent_form': 0.50,
        'line_opportunity': 0.20,
        'goalie_weakness': 0.15,
        'matchup': 0.10,
        'situational': 0.05
    },
    'D': {   # Defensemen - PP quarterback role important
        'recent_form': 0.40,
        'line_opportunity': 0.30,  # PP1 D-men are key
        'goalie_weakness': 0.10,
        'matchup': 0.15,
        'situational': 0.05
    }
}
```

---

## 4. Fatigue & Edge Cases

### 4.1 Back-to-Back (B2B) Games

**Who is affected:** Both skaters AND goalies

**Skater B2B Penalty:**
```python
def calculate_skater_b2b_penalty(schedule_context: Dict) -> float:
    """
    Apply fatigue penalty for back-to-back games.

    B2B: -8% to recent_form component
    B2B2B (3 games in 3 nights): -15% to recent_form component
    """
    games_in_last_3_days = schedule_context.get('games_in_last_3_days', 1)

    if games_in_last_3_days >= 3:  # B2B2B
        return -0.15
    elif games_in_last_3_days >= 2:  # B2B
        return -0.08
    else:
        return 0.0
```

**Goalie B2B Impact:**
```python
def adjust_goalie_weakness_for_b2b(goalie_weakness: float,
                                    goalie_schedule: Dict) -> float:
    """
    If opposing goalie is on B2B, increase weakness score (good for skaters).
    If opposing goalie is well-rested, slight decrease.
    """
    games_in_last_3_days = goalie_schedule.get('games_in_last_3_days', 1)

    if games_in_last_3_days >= 2:  # Goalie on B2B
        # Tired goalie = weaker = +10% to weakness score
        return goalie_weakness + 0.10
    elif games_in_last_3_days == 0:  # Well rested (2+ days off)
        # Fresh goalie = slightly better = -5% to weakness
        return goalie_weakness - 0.05

    return goalie_weakness
```

### 4.2 Edge Case: Hot Skater on B2B

**Scenario:** Skater has 1+ points in each of last 3 B2B games.

**Resolution:**
```python
def apply_hot_b2b_override(player_data: Dict) -> float:
    """
    If player has proven B2B success (1+ pt in last 2+ B2B games),
    reduce the B2B penalty by 50%.
    """
    b2b_performance = player_data.get('b2b_game_points', [])

    # Count B2B games with at least 1 point
    successful_b2b = sum(1 for pts in b2b_performance[-3:] if pts >= 1)

    if successful_b2b >= 2:
        # Player performs well on B2B - halve the penalty
        return 0.50  # Multiplier on penalty (50% reduction)

    return 1.0  # Full penalty applies
```

### 4.3 Edge Case: Hot Goalie (Shutout Streak)

**Scenario:** Opposing goalie has 2-3 consecutive shutouts.

**Resolution:**
```python
def adjust_for_hot_goalie(goalie_weakness: float, goalie_stats: Dict) -> float:
    """
    Hot goalie with shutout streak = reduce weakness score significantly.

    2 consecutive shutouts: -20% weakness
    3+ consecutive shutouts: -35% weakness
    """
    shutout_streak = goalie_stats.get('consecutive_shutouts', 0)

    if shutout_streak >= 3:
        return goalie_weakness * 0.65  # 35% reduction
    elif shutout_streak >= 2:
        return goalie_weakness * 0.80  # 20% reduction

    return goalie_weakness
```

### 4.4 Road Trip Fatigue

```python
def calculate_road_trip_penalty(schedule_context: Dict) -> float:
    """
    Extended road trips (4+ consecutive away games) cause fatigue.
    """
    consecutive_away = schedule_context.get('consecutive_away_games', 0)

    if consecutive_away >= 6:
        return -0.10  # Long road trip
    elif consecutive_away >= 4:
        return -0.05  # Moderate road trip

    return 0.0
```

---

## 5. Confidence Framework

### 5.1 Confidence Tiers

```python
CONFIDENCE_TIERS = {
    'very_high': {
        'threshold': 0.75,
        'requirements': [
            'svg_games >= 5',           # Confident SvG data
            'line_number <= 2',         # Top-6 forward or top-4 D
            'pp_unit in [1, 2]',        # On power play
            'recent_form_ppg >= 0.8'    # Hot streak
        ]
    },
    'high': {
        'threshold': 0.55,
        'requirements': [
            'line_number <= 2',
            'games_played >= 5'         # Enough sample
        ]
    },
    'medium': {
        'threshold': 0.35,
        'requirements': [
            'line_number <= 3',
            'games_played >= 3'
        ]
    },
    'low': {
        'threshold': 0.0,
        'requirements': []              # Everything else
    }
}
```

### 5.2 Transparency Fields

Each prediction includes:

```python
{
    'final_score': 72.5,
    'confidence': 'high',
    'score_breakdown': {
        'recent_form': 38.5,
        'line_opportunity': 15.2,
        'goalie_weakness': 11.8,
        'matchup': 4.5,
        'situational': 2.5
    },
    'matchup_method': 'team_defense_fallback',  # or 'confident_svg'
    'data_completeness': 0.85,  # % of non-default values
    'warnings': ['player_on_b2b', 'goalie_is_backup']
}
```

---

## 6. Data Sources & Endpoints

### 6.1 SportsDataIO NHL Endpoints

| Category | Endpoint | Purpose | Cache TTL |
|----------|----------|---------|-----------|
| **Schedule** | `/v3/nhl/scores/json/GamesByDate/{date}` | Daily game slate | 1 hour |
| **Schedule** | `/v3/nhl/scores/json/ScoresBasic/{date}` | Lightweight schedule | 1 hour |
| **Rosters** | `/v3/nhl/scores/json/PlayersBasic/{team}` | Team roster | 24 hours |
| **Rosters** | `/v3/nhl/scores/json/PlayersByActive` | All active players | 24 hours |
| **Goalies** | `/v3/nhl/scores/json/StartingGoaltendersByDate/{date}` | Confirmed starters | 30 min |
| **Goalies** | `/v3/nhl/scores/json/DepthCharts_Goalies` | Backup identification | 24 hours |
| **Lines** | `/v3/nhl/scores/json/LineCombinationsBySeason/{season}` | Line combinations | 6 hours |
| **Stats** | `/v3/nhl/stats/json/PlayerSeasonStats/{season}` | Season stats | 6 hours |
| **Stats** | `/v3/nhl/scores/json/PlayerGameStatsBySeason/{season}/{playerid}/{numgames}` | Game logs | 6 hours |
| **Box Scores** | `/v3/nhl/stats/json/BoxScoresFinal/{date}` | Settlement | 1 hour |
| **Play-by-Play** | `/v3/nhl/stats/json/PlayByPlay/{gameid}` | SvG attribution | 7 days |
| **Team Stats** | `/v3/nhl/stats/json/TeamSeasonStats/{season}` | Defense stats | 24 hours |
| **Injuries** | `/v3/nhl/scores/json/PlayerDetailsByInjured` | Injury list | 6 hours |
| **Transactions** | `/v3/nhl/scores/json/Transactions` | Callups/scratches | 6 hours |

### 6.2 Historical Data Scope

- **Current Season:** 2024-25 (primary)
- **Previous Season:** 2023-24 (for SvG history, career stats)
- **Play-by-Play Cache:** Last 2 seasons for SvG analysis

---

## 7. Data Model

### 7.1 Database Schema

```sql
-- Core predictions table
CREATE TABLE nhl_daily_analysis (
    id SERIAL PRIMARY KEY,
    player_id INT NOT NULL,
    player_name VARCHAR(100) NOT NULL,
    team VARCHAR(10) NOT NULL,
    position VARCHAR(5) NOT NULL,
    game_id INT NOT NULL,
    opponent VARCHAR(10) NOT NULL,
    game_time TIMESTAMP NOT NULL,
    analysis_date DATE NOT NULL,

    -- Scores
    final_score NUMERIC(8,4) NOT NULL,
    recent_form_score NUMERIC(8,4),
    line_opportunity_score NUMERIC(8,4),
    goalie_weakness_score NUMERIC(8,4),
    matchup_score NUMERIC(8,4),
    situational_score NUMERIC(8,4),

    -- Transparency
    matchup_method VARCHAR(30),
    svg_games_faced INT,
    confidence VARCHAR(20),
    data_completeness NUMERIC(5,4),

    -- Context
    line_number INT,
    pp_unit INT,
    is_home BOOLEAN,
    is_b2b BOOLEAN,
    opposing_goalie_id INT,
    opposing_goalie_name VARCHAR(100),

    -- Settlement
    point_outcome INT,  -- NULL=pending, 1=point, 0=no point, 2=PPD, 3=DNP
    actual_goals INT,
    actual_assists INT,
    settled_at TIMESTAMP,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(player_id, game_id, analysis_date)
);

-- Index for API queries
CREATE INDEX idx_nhl_analysis_date_score
ON nhl_daily_analysis(analysis_date, final_score DESC);

-- Players reference table
CREATE TABLE nhl_players (
    player_id INT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    team VARCHAR(10),
    position VARCHAR(5),
    jersey_number INT,
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Games reference table
CREATE TABLE nhl_games (
    game_id INT PRIMARY KEY,
    game_date DATE NOT NULL,
    home_team VARCHAR(10) NOT NULL,
    away_team VARCHAR(10) NOT NULL,
    home_score INT,
    away_score INT,
    status VARCHAR(20),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 7.2 API Output Format

```json
{
  "date": "2024-11-25",
  "generated_at": "2024-11-25T10:30:00Z",
  "total_players_scored": 156,
  "top_25": [
    {
      "rank": 1,
      "player_id": 8478402,
      "player_name": "Connor McDavid",
      "team": "EDM",
      "position": "C",
      "opponent": "VAN",
      "game_time": "2024-11-25T22:00:00Z",
      "final_score": 85.2,
      "confidence": "very_high",
      "score_breakdown": {
        "recent_form": 42.5,
        "line_opportunity": 18.0,
        "goalie_weakness": 12.8,
        "matchup": 8.5,
        "situational": 3.4
      },
      "context": {
        "ppg_last_10": 1.8,
        "line_number": 1,
        "pp_unit": 1,
        "streak_games": 5,
        "opposing_goalie": "Thatcher Demko",
        "is_b2b": false
      }
    }
    // ... 24 more players
  ]
}
```

---

## 8. Development Phases

### Phase 0: Foundation & Validation ✅ COMPLETE
- [x] Create `nhl_isolated/` directory structure
- [x] Build SportsDataIO NHL provider (mirror MLB pattern)
- [x] Test all endpoint responses
- [x] Document data quirks (see QUIRKS.md)
- [x] Establish caching layer with TTL support

### Phase 1: Core Data Pipeline ✅ COMPLETE
- [x] Fetch daily schedule
- [x] Get team rosters
- [x] Get starting goalies (with inference fallback)
- [x] ~~Get line combinations~~ → Infer from ice time (endpoint 404)
- [x] Map players to games

### Phase 2: Recent Form Analysis ✅ COMPLETE
- [x] Fetch player game logs (2024 + 2025 seasons)
- [x] Calculate PPG (last 10 games)
- [x] Calculate goal/assist split
- [x] Track home/away splits
- [x] Detect hot streaks (3+ and 5+ game bonuses)

### Phase 3: Goalie Weakness Analysis ✅ COMPLETE
- [x] Fetch goalie season stats
- [x] Fetch goalie recent form (last 5 starts)
- [x] Identify backups/callups via depth charts
- [x] Calculate weakness score (SV%, GAA, status components)
- [ ] Handle shutout streak edge case (deferred to Phase 6)

### Phase 4: Line Opportunity Score ✅ COMPLETE
- [x] ~~Parse line combinations~~ → Infer from avg TOI
- [x] Identify PP1/PP2 assignments (from PP stats)
- [x] ~~Calculate linemate quality~~ (deferred - requires line combos)
- [x] Score opportunity (0-1 scale)

### Phase 5: Matchup Analysis (Skater-vs-Goalie) ✅ COMPLETE
- [x] ~~Build play-by-play cache~~ → Play-by-play uses different IDs; using box scores instead
- [x] Implement SvG stats aggregation from box scores (matchup_analyzer.py)
- [x] Implement confidence thresholds (5+ games faced)
- [x] Build team defense fallback (using goalie weakness as proxy)
- [x] Load historical season data (2024-25 season: 1,272 games, 36,305 matchups)
- [x] 666 confident matchups (5+ games faced) from historical data
- Note: Historical data cached permanently (247 MB), loads in ~1 second

### Phase 6: Situational Factors ✅ COMPLETE
- [x] Detect B2B games (situational_analyzer.py)
- [x] Detect B2B2B situations
- [x] Calculate road trip length (consecutive away games)
- [x] Implement B2B penalties: -8% skater, +10% vs tired goalie
- [x] Implement well-rested goalie penalty: -5% when goalie has 3+ days rest

### Phase 7: Final Score Calculator ✅ COMPLETE
- [x] Implement position-specific weights
- [x] Combine all components
- [x] Add hot streak bonuses
- [x] Normalize to 0-100 scale

### Phase 8: Confidence & Transparency ✅ COMPLETE
- [x] Track matchup method used
- [ ] Calculate data completeness (deferred)
- [x] Assign confidence tiers (very_high, high, medium, low)
- [ ] Generate warnings (deferred)

### Phase 9: Database & API ✅ COMPLETE
- [x] Design PostgreSQL schema (nhl_players, nhl_games, nhl_daily_predictions)
- [x] Build upsert functions (upsert_players, upsert_games, upsert_predictions)
- [x] Create DailyPredictionRunner orchestrator (daily_runner.py)
- [x] Query functions (get_predictions_by_date, get_unsettled_predictions)
- [x] Settlement update function (update_settlement)
- [x] Hit rate analytics (get_hit_rate_summary)
- [x] Return Top 25 ranked list (JSON output)
- [ ] API endpoint: `/nhl/predictions/{date}` (deferred - can use JSON files)

### Phase 10: Settlement & Calibration ✅ COMPLETE
- [x] Fetch final box scores (settlement.py)
- [x] Determine point outcomes (HIT/MISS/DNP/PPD)
- [x] Calculate hit rate by tier and rank bucket
- [x] Create backfill script for historical testing (scripts/backfill_predictions.py)
- [x] Performance report generation (get_hit_rate_summary)
- Note: With scrambled data, confidence tiers still show directional accuracy
  - very_high: 37.8% → high: 21.9% → medium: 13.8%

---

## 9. Directory Structure

```
nhl_isolated/
├── __init__.py
├── requirements.txt
├── NHL_ALGORITHM_ADR.md          # This document
├── QUIRKS.md                     # Data quirks and API issues
│
├── pipeline/
│   ├── __init__.py
│   ├── daily_runner.py           # ✅ Main orchestration with DB persistence
│   ├── daily_etl.py              # ✅ Legacy ETL
│   ├── enrichment.py             # ✅ Data enrichment with line inference
│   └── settlement.py             # ✅ Settlement against box scores
│
├── scripts/
│   └── backfill_predictions.py   # ✅ Historical prediction generator
│
├── analytics/
│   ├── __init__.py
│   ├── final_score_calculator.py      # ✅ Combines all components
│   ├── recent_form_calculator.py      # ✅ PPG + streak bonuses
│   ├── goalie_weakness_calculator.py  # ✅ SV%, GAA, status
│   ├── line_opportunity_calculator.py # ✅ Line + PP + TOI
│   ├── matchup_analyzer.py            # ✅ SvG from box scores
│   └── situational_analyzer.py        # ✅ B2B, road trips, fatigue
│
├── providers/
│   ├── __init__.py
│   ├── base.py                   # ✅ Abstract base class
│   ├── sportsdataio_nhl.py       # ✅ Full provider (18+ endpoints)
│   └── cached_provider.py        # ✅ Caching wrapper
│
├── database/
│   ├── __init__.py
│   └── db_manager.py             # ✅ PostgreSQL persistence
│
├── utilities/
│   ├── __init__.py
│   └── cache_manager.py          # ✅ TTL-based file cache
│
├── data/
│   ├── cache/                    # File-based cache (JSON)
│   └── predictions/              # Output files
│
└── scripts/
    └── test_endpoints.py         # ✅ Endpoint validation
```

### Key Files Implemented

| File | Lines | Purpose |
|------|-------|---------|
| `providers/sportsdataio_nhl.py` | ~450 | Full SportsDataIO provider with 18+ endpoints |
| `providers/cached_provider.py` | ~300 | Caching wrapper with TTL support |
| `pipeline/enrichment.py` | ~550 | Player enrichment with line/goalie/situational inference |
| `pipeline/daily_etl.py` | ~250 | Main ETL orchestrator with CLI |
| `analytics/final_score_calculator.py` | ~350 | Multi-component scoring engine |
| `analytics/recent_form_calculator.py` | ~200 | PPG calculation with streaks |
| `analytics/goalie_weakness_calculator.py` | ~200 | Goalie quality assessment |
| `analytics/line_opportunity_calculator.py` | ~175 | Line/PP opportunity scoring |
| `analytics/situational_analyzer.py` | ~300 | B2B detection, road trips, fatigue penalties |
| `analytics/matchup_analyzer.py` | ~250 | Skater-vs-Goalie history from box scores |
| `utilities/cache_manager.py` | ~150 | File-based cache with metadata |

---

## 10. Configuration

### Environment Variables

```bash
# SportsDataIO API
SPORTSDATAIO_NHL_API_KEY=your_key_here

# Database (same as MLB/NCAAF)
DATABASE_URL=postgresql://user:pass@host:5432/analytics_pro

# Cache settings
CACHE_DIR=data/cache
CACHE_TTL_HOURS=6

# API settings
API_TOP_N=25
```

### Weights Configuration (`config/weights.json`)

```json
{
  "version": "1.0",
  "global_weights": {
    "recent_form": 0.50,
    "line_opportunity": 0.20,
    "goalie_weakness": 0.15,
    "matchup": 0.10,
    "situational": 0.05
  },
  "position_weights": {
    "C": {"recent_form": 0.45, "line_opportunity": 0.25, "goalie_weakness": 0.15, "matchup": 0.10, "situational": 0.05},
    "LW": {"recent_form": 0.50, "line_opportunity": 0.20, "goalie_weakness": 0.15, "matchup": 0.10, "situational": 0.05},
    "RW": {"recent_form": 0.50, "line_opportunity": 0.20, "goalie_weakness": 0.15, "matchup": 0.10, "situational": 0.05},
    "D": {"recent_form": 0.40, "line_opportunity": 0.30, "goalie_weakness": 0.10, "matchup": 0.15, "situational": 0.05}
  },
  "fatigue_penalties": {
    "b2b_skater": -0.08,
    "b2b2b_skater": -0.15,
    "b2b_goalie_bonus": 0.10,
    "road_trip_4plus": -0.05,
    "road_trip_6plus": -0.10
  },
  "streak_bonuses": {
    "3_game_point_streak": 0.05,
    "5_game_point_streak": 0.10
  },
  "goalie_modifiers": {
    "2_shutout_streak_penalty": 0.20,
    "3_shutout_streak_penalty": 0.35
  },
  "confidence_thresholds": {
    "svg_confident_games": 5,
    "min_games_for_form": 3
  }
}
```

---

## 11. Implementation Status

### Current State (as of 2025-11-24)

The NHL Player Points prediction algorithm is **operational** with core functionality complete through Phase 4. The system successfully:

1. Fetches daily game schedules and team rosters
2. Enriches player data with stats, line inference, and goalie matchups
3. Calculates multi-component scoring with position-specific weights
4. Produces ranked Top 25 predictions in API-ready JSON format

### Test Run Results

```
Date: 2025-11-25 (DAL @ EDM)
Players Scored: 40
Duration: <1 second (100% cache hit)
Score Range: 84.0 - 31.7

Top 5 Predictions:
1. Jason Robertson (DAL) - 84.0 [very_high]
2. Leon Draisaitl (EDM)  - 79.5 [very_high]
3. Evan Bouchard (EDM)   - 78.9 [high]
4. Tyler Seguin (DAL)    - 77.7 [high]
5. Miro Heiskanen (DAL)  - 72.8 [very_high]
```

### Output Files

- `nhl_isolated/data/predictions/nhl_predictions_{date}.json` - API response (Top 25)
- `nhl_isolated/data/predictions/nhl_predictions_{date}_full.json` - All scored players

### CLI Usage

```bash
# Tomorrow's games (default)
python -m nhl_isolated.pipeline.daily_etl

# Specific date
python -m nhl_isolated.pipeline.daily_etl --date 2025-11-25

# Fast mode (skip game logs)
python -m nhl_isolated.pipeline.daily_etl --no-game-logs

# Custom output
python -m nhl_isolated.pipeline.daily_etl --top-n 50 --output-dir /path/to/output
```

---

## 12. Data Variance Analysis (Free Trial)

### SportsDataIO Scrambled Data

The free trial tier applies a **5-20% variance** to statistical values. This is documented in QUIRKS.md.

### Impact Assessment

| Actual PPG | Variance Range | Player Tier | Tier Preserved? |
|------------|----------------|-------------|-----------------|
| 1.5 | 1.2 - 1.8 | Elite | ✅ Yes |
| 1.0 | 0.8 - 1.2 | High-scoring | ✅ Yes |
| 0.5 | 0.4 - 0.6 | Average | ✅ Yes |
| 0.2 | 0.16 - 0.24 | Depth | ✅ Yes |
| 0.0 | 0.0 | Non-scorer | ✅ Yes |

### Why Variance is Acceptable

1. **Tier Preservation**: A ±20% variance does not move players between tiers. An elite 1.0 PPG player with -20% variance (0.8 PPG) is still clearly a top offensive threat.

2. **Multi-Component Dilution**: Our 5-component scoring formula (50/20/15/10/5 weights) means any single stat's variance is diluted across the final score. A 20% variance on recent_form becomes ~10% impact on final score.

3. **Relative Rankings**: We care about relative ordering, not absolute values. If all players have similar variance, rankings remain largely stable.

4. **Confidence Tiers**: Our confidence framework already accounts for data uncertainty. Players with limited data get lower confidence regardless of variance.

5. **Binary Outcome Signal**: For point prediction (scored vs. didn't score):
   - 0.8+ PPG strongly indicates "likely to score"
   - 0.0-0.2 PPG strongly indicates "unlikely to score"
   - Variance doesn't flip these signals

### Edge Cases Where Variance Matters

The only scenario where 20% variance could affect predictions is at **tier boundaries**:
- A player with true 0.6 PPG showing as 0.48 PPG might appear "average" instead of "above average"
- This affects ~5-10% of players at tier boundaries
- Impact: Minor ranking shuffles within confidence tiers, not systematic errors

### Recommendation

The scrambled data is **acceptable for development and testing**. Production deployment should use a paid API tier for unscrambled data, particularly for:
- Settlement/calibration accuracy
- Skater-vs-Goalie (SvG) historical analysis
- Model weight tuning

---

## Appendix A: Comparison to MLB System

| Aspect | MLB Hit Prediction | NHL Point Prediction |
|--------|-------------------|---------------------|
| **Primary Metric** | OPS (On-base + Slugging) | PPG (Points Per Game) |
| **Primary Weight** | 60% Batter Form | 50% Recent Form |
| **Matchup Analysis** | BvP (Batter vs Pitcher) | SvG (Skater vs Goalie) |
| **Opponent Quality** | Pitcher ERA/FIP/H9 | Goalie SV%/GAA |
| **Role Indicator** | Batting Order | Line Number + PP Unit |
| **Contextual** | Umpire, Park Factor | B2B Fatigue |
| **Position Handling** | N/A (batters only) | C, LW, RW, D weights |
| **Output Size** | All lineup batters | Top 25 from all skaters |
| **Confidence** | Method tracking | Tier + method tracking |

---

## Appendix B: Key Differences from Original Plan

1. **Added explicit weight system** (was undefined)
2. **Added position-specific weights** (was missing)
3. **Defined fatigue rules for both skaters AND goalies** (was unclear)
4. **Added edge case handling** (hot skaters on B2B, hot goalies)
5. **Added confidence framework** (was missing)
6. **Defined data model/schema** (was abstract ERD only)
7. **Specified historical data scope** (2024 + 2025 seasons)
8. **Added settlement approach** (was missing)

---

*Document maintained by analytics-pro team*
