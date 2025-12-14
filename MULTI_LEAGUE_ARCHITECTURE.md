# SGP Engine - Multi-League Architecture

## Executive Summary

This document outlines how to generalize the SGP Edge Engine across multiple sports leagues (NFL, NBA, MLB, NHL, NCAAF, NCAAB) while maintaining a unified landing page experience.

**Core Insight**: The market-first, edge-detection philosophy is sport-agnostic. The 5 signal types (trend, usage, matchup, environment, correlation) are conceptually universal - only their implementations differ per sport.

---

## 1. Universal Philosophy

These principles apply to ALL sports:

### 1.1 Market-First Approach
```
Sportsbooks set efficient lines. Don't fight them on base projections.
Instead, find systematic edges where YOUR data disagrees with the market.
```

### 1.2 Edge Detection > Prediction
| Don't Do This | Do This Instead |
|---------------|-----------------|
| "LeBron will score 28.5 points" | "LeBron's line is 5% too low because..." |
| Build complex prediction models | Find deviations from market consensus |
| Require sport-specific ML models | Apply universal signal framework |

### 1.3 Evidence-Based Reasoning
Every recommendation must answer: **"Why should I bet this?"**
- Primary reason (strongest signal)
- Supporting reasons (confirming signals)
- Risk factors (what could go wrong)

### 1.4 The 80/20 Rule
Most props are priced efficiently. Focus only on:
- High-signal situations (≥5% edge)
- Explainable edges (clear "because X")
- Correlated props (game script alignment)

---

## 2. Universal Signal Framework

### 2.1 The 5 Signals

| Signal | What It Detects | Universal? |
|--------|-----------------|------------|
| **Trend** | Recent performance vs season average | ✅ Yes |
| **Usage** | Volume/opportunity changes | ✅ Yes |
| **Matchup** | Opponent strength vs stat type | ✅ Yes |
| **Environment** | External factors (weather, rest, venue) | ✅ Yes |
| **Correlation** | Game-level factors (total, spread) | ✅ Yes |

### 2.2 Signal Interface (Abstract)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class SignalResult:
    """Universal signal output."""
    signal_type: str           # 'trend', 'usage', 'matchup', 'environment', 'correlation'
    strength: float            # -1.0 to +1.0 (negative=under, positive=over)
    confidence: float          # 0.0 to 1.0
    evidence: str              # Human-readable explanation
    raw_data: Optional[dict]   # Sport-specific supporting data

class BaseSignal(ABC):
    """Abstract base for all signals across all sports."""

    @abstractmethod
    def calculate(self, player_id: str, stat_type: str, line: float) -> SignalResult:
        """Calculate signal for a specific prop."""
        pass
```

---

## 3. Sport-Specific Adaptations

### 3.1 Trend Signal

| Sport | Lookback Window | Key Metrics | Notes |
|-------|-----------------|-------------|-------|
| NFL | Last 3 games | Stats per game | Short season, high variance |
| NBA | Last 5-10 games | Stats per game, per 36 min | 82-game season, more data |
| MLB | Last 10-15 games | Stats per PA, per game | 162 games, huge sample |
| NHL | Last 5-7 games | Stats per game, TOI-adjusted | 82 games, line changes matter |
| NCAAF | Last 3 games | Stats per game | Like NFL, high variance |
| NCAAB | Last 5 games | Stats per game, per 40 min | Shorter season than NBA |

### 3.2 Usage Signal

| Sport | Primary Usage Metrics | Secondary Metrics |
|-------|----------------------|-------------------|
| NFL | Targets, carries, snap% | Route participation, red zone share |
| NBA | Minutes, usage rate, shot attempts | Touch time, possessions |
| MLB | Plate appearances, batting order | Lineup position, days rest |
| NHL | TOI, shifts, PP/PK time | Line assignment, deployment |
| NCAAF | Targets, carries, snap% | Same as NFL |
| NCAAB | Minutes, shot attempts | Similar to NBA |

### 3.3 Matchup Signal

| Sport | Matchup Analysis | Data Source |
|-------|------------------|-------------|
| NFL | Defensive rankings by position (QB/RB/WR/TE) | nflreadpy PBP |
| NBA | Defensive rating, pace, position defense | nba_api |
| MLB | Pitcher vs batter splits, park factors | pybaseball |
| NHL | Goalie stats, team defense, shot suppression | nhl_api |
| NCAAF | Similar to NFL but less data | cfbd |
| NCAAB | KenPom ratings, defensive efficiency | kenpom_api |

### 3.4 Environment Signal

| Sport | Key Factors |
|-------|-------------|
| NFL | Weather (wind, cold, rain), dome, altitude |
| NBA | Back-to-back, rest days, altitude (Denver), travel |
| MLB | Weather, park factors, day/night, pitcher handedness |
| NHL | Back-to-back, travel, altitude |
| NCAAF | Weather, altitude, home field advantage |
| NCAAB | Home court, altitude, travel |

### 3.5 Correlation Signal

| Sport | Game Total Impact | Spread/Line Impact |
|-------|-------------------|-------------------|
| NFL | High total → more passing yards, TDs | Favorite → more rushing, clock control |
| NBA | High total → more points for stars | Blowout → bench minutes, reduced stats |
| MLB | High total → more hits, runs | Big favorite → closer may not pitch |
| NHL | High total → more goals, assists | Favorite → more offensive zone time |

---

## 4. Prop Types by Sport

### 4.1 NFL
```python
NFL_PROP_TYPES = {
    'passing': ['pass_yds', 'pass_tds', 'completions', 'pass_attempts', 'interceptions'],
    'rushing': ['rush_yds', 'rush_attempts', 'rush_tds', 'longest_rush'],
    'receiving': ['rec_yds', 'receptions', 'rec_tds', 'longest_reception'],
    'defense': ['sacks', 'interceptions', 'tackles'],
    'special': ['anytime_td', 'first_td', 'last_td'],
}
```

### 4.2 NBA
```python
NBA_PROP_TYPES = {
    'scoring': ['points', 'three_pointers_made', 'free_throws_made'],
    'rebounds': ['rebounds', 'offensive_rebounds', 'defensive_rebounds'],
    'assists': ['assists'],
    'defense': ['steals', 'blocks'],
    'combo': ['pts_rebs_asts', 'pts_rebs', 'pts_asts', 'rebs_asts'],
    'other': ['turnovers', 'fouls'],
}
```

### 4.3 MLB
```python
MLB_PROP_TYPES = {
    'batting': ['hits', 'total_bases', 'rbis', 'runs', 'home_runs', 'stolen_bases'],
    'pitching': ['strikeouts', 'earned_runs', 'hits_allowed', 'walks'],
    'combo': ['hits_runs_rbis'],
}
```

### 4.4 NHL
```python
NHL_PROP_TYPES = {
    'skater': ['goals', 'assists', 'points', 'shots_on_goal', 'blocked_shots'],
    'goalie': ['saves', 'goals_against'],
}
```

---

## 5. Data Provider Interface

Each sport needs a data provider that implements this interface:

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import date

class SportDataProvider(ABC):
    """Abstract interface for sport-specific data providers."""

    @property
    @abstractmethod
    def league(self) -> str:
        """Return league identifier ('NFL', 'NBA', 'MLB', 'NHL')."""
        pass

    @abstractmethod
    def get_player_stats(
        self,
        player_id: str,
        season: int,
        last_n_games: Optional[int] = None
    ) -> List[Dict]:
        """Get player game logs."""
        pass

    @abstractmethod
    def get_team_defense(self, team: str, season: int) -> Dict:
        """Get team defensive statistics."""
        pass

    @abstractmethod
    def get_schedule(self, season: int, date: Optional[date] = None) -> List[Dict]:
        """Get games for a date or full schedule."""
        pass

    @abstractmethod
    def get_prop_types(self) -> List[str]:
        """Return supported prop types for this sport."""
        pass

# Implementations
class NFLDataProvider(SportDataProvider):
    """Uses nflreadpy."""
    league = 'NFL'

class NBADataProvider(SportDataProvider):
    """Uses nba_api."""
    league = 'NBA'

class MLBDataProvider(SportDataProvider):
    """Uses pybaseball."""
    league = 'MLB'

class NHLDataProvider(SportDataProvider):
    """Uses nhl_api or hockey_scraper."""
    league = 'NHL'
```

---

## 6. Unified Database Schema

### 6.1 Multi-League Tables

```sql
-- Parlays table with league support
CREATE TABLE sgp_parlays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- League identification (NEW)
    league VARCHAR(10) NOT NULL,  -- 'NFL', 'NBA', 'MLB', 'NHL', 'NCAAF', 'NCAAB'

    -- Game identification
    game_id VARCHAR(100) NOT NULL,
    game_date DATE NOT NULL,
    game_time TIMESTAMPTZ,
    home_team VARCHAR(50) NOT NULL,
    away_team VARCHAR(50) NOT NULL,

    -- Parlay details
    parlay_type VARCHAR(50) NOT NULL,
    total_legs INTEGER NOT NULL,
    combined_odds INTEGER,
    implied_probability DECIMAL(10, 6),
    thesis TEXT,

    -- Temporal (flexible for different sports)
    season INTEGER NOT NULL,
    period VARCHAR(20),  -- 'week_15', 'dec_15', 'game_42', etc.

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_parlay UNIQUE (league, season, period, parlay_type, game_id)
);

-- Index for cross-league queries
CREATE INDEX idx_parlays_league_date ON sgp_parlays(league, game_date);
CREATE INDEX idx_parlays_date ON sgp_parlays(game_date);
```

### 6.2 Period Conventions by Sport

| Sport | Period Format | Example |
|-------|---------------|---------|
| NFL | `week_{n}` | `week_15` |
| NBA | `{month}_{day}` or `week_{n}` | `dec_15` or `week_10` |
| MLB | `{month}_{day}` | `aug_15` |
| NHL | `{month}_{day}` | `jan_20` |
| NCAAF | `week_{n}` | `week_12` |
| NCAAB | `{month}_{day}` | `mar_15` |

---

## 7. Unified Landing Page Architecture

### 7.1 Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        DAILY ORCHESTRATOR                               │
├─────────────────────────────────────────────────────────────────────────┤
│  Runs each league's SGP engine based on game schedule                   │
│                                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │   NFL   │  │   NBA   │  │   MLB   │  │   NHL   │  │  NCAAB  │       │
│  │ Engine  │  │ Engine  │  │ Engine  │  │ Engine  │  │ Engine  │       │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘       │
│       │            │            │            │            │             │
│       └────────────┴────────────┴────────────┴────────────┘             │
│                                 │                                       │
│                                 ▼                                       │
│                    ┌─────────────────────────┐                          │
│                    │   UNIFIED DATABASE      │                          │
│                    │   (sgp_parlays table)   │                          │
│                    └────────────┬────────────┘                          │
│                                 │                                       │
│                                 ▼                                       │
│                    ┌─────────────────────────┐                          │
│                    │   UNIFIED API           │                          │
│                    │   /api/sgp/today        │                          │
│                    └─────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        LANDING PAGE                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  TODAY'S SGP RECOMMENDATIONS                     Dec 15, 2025   │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │                                                                 │   │
│  │  🏈 NFL                                          [View League →]│   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │ MIN @ DAL (SNF) - Primary Parlay                        │   │   │
│  │  │ • J. Jefferson receptions UNDER 5.5                     │   │   │
│  │  │ • K. Turpin rush attempts OVER 1.5                      │   │   │
│  │  │ Edge: 6.5% | 4 legs                                     │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                                                                 │   │
│  │  🏀 NBA                                          [View League →]│   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │ LAL @ BOS - Primary Parlay                              │   │   │
│  │  │ • LeBron James points OVER 26.5                         │   │   │
│  │  │ • Jayson Tatum rebounds OVER 7.5                        │   │   │
│  │  │ Edge: 7.2% | 3 legs                                     │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                                                                 │   │
│  │  ⚾ MLB                                          [View League →]│   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │ No games today (offseason)                              │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                                                                 │   │
│  │  🏒 NHL                                          [View League →]│   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │ TOR @ MTL - Primary Parlay                              │   │   │
│  │  │ • A. Matthews goals OVER 0.5                            │   │   │
│  │  │ • N. Suzuki assists OVER 0.5                            │   │   │
│  │  │ Edge: 5.8% | 3 legs                                     │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                                                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 API Endpoints

```
GET /api/sgp/today
Returns all parlays for today across all leagues

GET /api/sgp/today?league=NFL
Returns today's NFL parlays only

GET /api/sgp/league/{league}/date/{date}
Returns parlays for a specific league and date

GET /api/sgp/leagues
Returns list of active leagues with today's game counts
```

### 7.3 Response Format

```json
{
  "date": "2025-12-15",
  "leagues": [
    {
      "league": "NFL",
      "display_name": "NFL Football",
      "icon": "🏈",
      "games_today": 1,
      "parlays": [
        {
          "id": "57ec0acf-...",
          "game": {
            "away_team": "MIN",
            "home_team": "DAL",
            "game_time": "2025-12-15T20:20:00Z",
            "display": "MIN @ DAL"
          },
          "parlay_type": "primary",
          "legs": [
            {
              "player": "Justin Jefferson",
              "team": "MIN",
              "prop": "receptions",
              "direction": "under",
              "line": 5.5,
              "edge_pct": 7.0
            }
          ],
          "avg_edge": 6.5,
          "thesis": "High total suggests offensive game..."
        }
      ],
      "league_url": "/nfl"
    },
    {
      "league": "NBA",
      "display_name": "NBA Basketball",
      "icon": "🏀",
      "games_today": 8,
      "parlays": [...],
      "league_url": "/nba"
    }
  ]
}
```

---

## 8. ATTD Pipeline Dependency

### 8.1 Current State (NFL Only)

The ATTD pipeline provides TD probability predictions that feed into SGP as an additional signal source. This is **NFL-specific**.

### 8.2 Generalization Strategy

Each sport can have its own "signature prop" pipeline:

| Sport | Signature Prop | Equivalent Pipeline |
|-------|----------------|---------------------|
| NFL | Anytime TD | ATTD Pipeline |
| NBA | Points/Double-Double | Points Projection Pipeline |
| MLB | Home Runs | HR Probability Pipeline |
| NHL | Goals | Goals Probability Pipeline |

**However, for V1 multi-league, we can skip sport-specific prediction pipelines** and rely purely on the 5-signal framework. The ATTD integration is an enhancement, not a requirement.

### 8.3 Recommendation

```
Phase 1: Pure Edge Detection (No sport-specific ML)
- Use 5 signal framework only
- Works immediately for any sport with Odds API coverage

Phase 2: Sport-Specific Enhancements
- Add ATTD-equivalent pipelines for key props per sport
- Integrate as additional signal source
```

---

## 9. Implementation Roadmap

### Phase 1: Core Abstraction (Foundation)
- [ ] Create abstract `SportDataProvider` interface
- [ ] Create abstract `BaseSignal` classes
- [ ] Refactor NFL implementation to use abstractions
- [ ] Add `league` field to database schema

### Phase 2: NBA Implementation (Highest ROI)
- [ ] Implement `NBADataProvider` (using nba_api)
- [ ] Adapt signal implementations for NBA
- [ ] Add NBA prop types to Odds API client
- [ ] Test with live NBA games

### Phase 3: Unified Landing Page
- [ ] Create `/api/sgp/today` endpoint
- [ ] Build cross-league frontend component
- [ ] Add league filtering and navigation

### Phase 4: Additional Sports
- [ ] NHL (similar structure to NBA)
- [ ] MLB (seasonal - spring 2026)
- [ ] NCAAF (fall 2026)
- [ ] NCAAB (November 2026)

---

## 10. Data Provider Availability

| Sport | Primary Provider | Backup | Notes |
|-------|------------------|--------|-------|
| NFL | nflreadpy | ESPN API | Excellent PBP data |
| NBA | nba_api | basketball_reference | Good stats, some rate limits |
| MLB | pybaseball | retrosheet | Excellent historical data |
| NHL | nhl_api | hockey_scraper | Decent coverage |
| NCAAF | cfbd | ESPN | Less detailed than NFL |
| NCAAB | kenpom, sports_reference | ESPN | Ratings available |

---

## 11. Odds API Coverage

The Odds API supports props for:
- ✅ NFL (comprehensive)
- ✅ NBA (comprehensive)
- ✅ MLB (comprehensive)
- ✅ NHL (moderate)
- ⚠️ NCAAF (limited props)
- ⚠️ NCAAB (limited props)

**Key insight**: Odds API is the unifying layer. If they have props, we can generate SGPs.

---

*Document Version: 1.0*
*Last Updated: December 2025*
