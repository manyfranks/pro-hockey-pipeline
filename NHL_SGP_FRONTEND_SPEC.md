# NHL SGP Frontend API Specification

**Version:** 1.0
**Last Updated:** December 13, 2025
**Base URL:** `https://[project-id].supabase.co/rest/v1`

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Core Endpoints](#core-endpoints)
4. [Response Models](#response-models)
5. [Query Examples](#query-examples)
6. [Real-time Subscriptions](#real-time-subscriptions)
7. [Frontend Components](#frontend-components)
8. [Error Handling](#error-handling)

---

## Overview

The NHL SGP (Same Game Parlay) API provides multi-leg parlay recommendations for NHL games. Architecture mirrors NFL/NCAAF SGP implementations for consistency.

### Key Features

- **Daily Parlay Generation**: New parlays at 9 AM ET each game day
- **3-4 Leg Parlays**: Optimized for validated markets (points, shots on goal)
- **Edge Threshold**: Only 10%+ edge legs included (validated 49.6% hit rate)
- **Thesis Narratives**: Each parlay includes analytical reasoning
- **Settlement Tracking**: Win/loss tracking with profit calculation

### Data Flow

```
Daily Pipeline (9 AM ET)
    ├── Settle yesterday's parlays
    └── Generate today's parlays
            ├── Fetch odds from Odds API
            ├── Calculate edges via 6-signal model
            ├── Select best 3-4 legs per game
            └── Write to nhl_sgp_parlays + nhl_sgp_legs
```

---

## Authentication

### Read Access (Public)

```bash
curl -X GET \
  'https://[project-id].supabase.co/rest/v1/nhl_sgp_parlays' \
  -H 'apikey: [anon-key]' \
  -H 'Authorization: Bearer [anon-key]'
```

### Environment Variables

```bash
NEXT_PUBLIC_SUPABASE_URL=https://[project-id].supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=[anon-key]
```

---

## Core Endpoints

### 1. Get Today's Parlays

**Endpoint:** `GET /nhl_sgp_parlays`

**Query:**
```http
GET /nhl_sgp_parlays?game_date=eq.2025-12-14&select=*,nhl_sgp_legs(*)&order=created_at.desc
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
    "game_slot": "EVENING",
    "total_legs": 3,
    "combined_odds": 450,
    "implied_probability": 0.1818,
    "thesis": "Offensive-focused parlay targeting point production | Stacking TOR players | Average edge: 14.2%",
    "season": 2025,
    "season_type": "regular",
    "created_at": "2025-12-14T14:00:00Z",
    "nhl_sgp_legs": [
      {
        "id": "b2c3d4e5-2222-4000-8000-000000000001",
        "leg_number": 1,
        "player_name": "Auston Matthews",
        "team": "TOR",
        "position": "C",
        "stat_type": "points",
        "line": 0.5,
        "direction": "over",
        "odds": -135,
        "edge_pct": 12.5,
        "confidence": 0.78,
        "model_probability": 0.5842,
        "market_probability": 0.5743,
        "primary_reason": "Season avg 1.2 pts is 140% above 0.5 line",
        "signals": {
          "line_value": {"strength": 0.95, "evidence": "Strong edge over line"},
          "trend": {"strength": 0.17, "evidence": "L5 trending up"},
          "matchup": {"strength": 0.20, "evidence": "MTL allows 3.4 GA/gm"}
        },
        "actual_value": null,
        "result": null
      }
    ]
  }
]
```

### 2. Get Parlays by Date Range

**Query:**
```http
GET /nhl_sgp_parlays?game_date=gte.2025-12-01&game_date=lte.2025-12-14&select=*,nhl_sgp_legs(*),nhl_sgp_settlements(*)
```

### 3. Get Primary Parlays Only

**Query:**
```http
GET /nhl_sgp_parlays?parlay_type=eq.primary&select=*,nhl_sgp_legs(*)&order=game_date.desc&limit=10
```

### 4. Get Settled Parlays with Results

**Query:**
```http
GET /nhl_sgp_parlays?select=*,nhl_sgp_legs(*),nhl_sgp_settlements!inner(*)&order=game_date.desc
```

**Response includes settlement:**
```json
{
  "id": "...",
  "nhl_sgp_legs": [...],
  "nhl_sgp_settlements": [
    {
      "id": "c3d4e5f6-3333-4000-8000-000000000001",
      "parlay_id": "a1b2c3d4-1111-4000-8000-000000000001",
      "legs_hit": 3,
      "total_legs": 3,
      "result": "WIN",
      "profit": 450.00,
      "settled_at": "2025-12-15T14:00:00Z"
    }
  ]
}
```

### 5. Get High-Edge Legs

**Query:**
```http
GET /nhl_sgp_legs?edge_pct=gte.12&order=edge_pct.desc&limit=20&select=*,nhl_sgp_parlays!inner(game_date,home_team,away_team)
```

### 6. Get Performance Summary (RPC)

**Query:**
```http
POST /rpc/get_nhl_sgp_performance
Content-Type: application/json

{
  "start_date": "2025-12-01",
  "end_date": "2025-12-14"
}
```

**Response:**
```json
{
  "total_parlays": 28,
  "wins": 4,
  "losses": 24,
  "win_rate": 14.3,
  "total_legs": 98,
  "legs_hit": 51,
  "leg_hit_rate": 52.0,
  "total_profit": 150.00,
  "avg_odds": 425
}
```

---

## Response Models

### Parlay Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_type` | string | `primary`, `theme_stack`, `value_play` |
| `game_id` | string | Unique game identifier |
| `game_date` | date | Game date (YYYY-MM-DD) |
| `home_team` | string | Team abbreviation (3 chars) |
| `away_team` | string | Team abbreviation (3 chars) |
| `game_slot` | string | `EVENING`, `AFTERNOON`, `MATINEE` |
| `total_legs` | integer | Number of legs (3-4) |
| `combined_odds` | integer | American odds (+450) |
| `implied_probability` | decimal | Win probability (0.1818) |
| `thesis` | string | Narrative explanation |
| `season` | integer | NHL season year |
| `season_type` | string | `regular`, `playoffs` |
| `created_at` | timestamp | Generation time |

### Leg Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_id` | UUID | FK to parlay |
| `leg_number` | integer | Order (1, 2, 3, 4) |
| `player_name` | string | Player display name |
| `team` | string | Team abbreviation |
| `position` | string | `C`, `LW`, `RW`, `D`, `G` |
| `stat_type` | string | `points`, `shots_on_goal` |
| `line` | decimal | Prop line (0.5, 3.5) |
| `direction` | string | `over` or `under` |
| `odds` | integer | American odds (-110) |
| `edge_pct` | decimal | Projected edge (12.5) |
| `confidence` | decimal | 0.0 to 1.0 |
| `primary_reason` | string | Main evidence |
| `signals` | JSONB | Full signal breakdown |
| `actual_value` | decimal | Post-game actual (null if unsettled) |
| `result` | string | `WIN`, `LOSS`, `PUSH`, `VOID`, null |

### Settlement Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `parlay_id` | UUID | FK to parlay |
| `legs_hit` | integer | Legs that hit |
| `total_legs` | integer | Total scoreable legs |
| `result` | string | `WIN`, `LOSS`, `VOID` |
| `profit` | decimal | At $100 stake |
| `settled_at` | timestamp | Settlement time |

### Signal Object (JSONB)

```json
{
  "line_value": {
    "strength": 0.95,
    "confidence": 0.90,
    "evidence": "Season avg 1.2 is 140% ABOVE line 0.5"
  },
  "trend": {
    "strength": 0.17,
    "confidence": 0.80,
    "evidence": "L5 avg 1.4 vs season 1.2 (UP 16.7%)"
  },
  "usage": {
    "strength": 0.15,
    "confidence": 0.85,
    "evidence": "PP1 deployment, 22:30 TOI/gm"
  },
  "matchup": {
    "strength": 0.20,
    "confidence": 0.75,
    "evidence": "MTL allows 3.4 goals/gm (bottom 10)"
  },
  "environment": {
    "strength": 0.10,
    "confidence": 0.70,
    "evidence": "No B2B, home game"
  },
  "correlation": {
    "strength": 0.08,
    "confidence": 0.65,
    "evidence": "High total correlates with points"
  }
}
```

---

## Query Examples

### TypeScript/React

```typescript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

// Get today's parlays
async function getTodaysParlays() {
  const today = new Date().toISOString().split('T')[0]

  const { data, error } = await supabase
    .from('nhl_sgp_parlays')
    .select(`
      *,
      nhl_sgp_legs (*)
    `)
    .eq('game_date', today)
    .eq('parlay_type', 'primary')
    .order('combined_odds', { ascending: false })

  return data
}

// Get settled parlays with results
async function getSettledParlays(limit = 20) {
  const { data, error } = await supabase
    .from('nhl_sgp_parlays')
    .select(`
      *,
      nhl_sgp_legs (*),
      nhl_sgp_settlements (*)
    `)
    .not('nhl_sgp_settlements', 'is', null)
    .order('game_date', { ascending: false })
    .limit(limit)

  return data
}

// Get performance stats
async function getPerformanceStats() {
  const { data, error } = await supabase
    .from('nhl_sgp_settlements')
    .select('result, profit')

  if (!data) return null

  const wins = data.filter(s => s.result === 'WIN').length
  const total = data.length
  const totalProfit = data.reduce((sum, s) => sum + (s.profit || 0), 0)

  return {
    total_parlays: total,
    wins,
    win_rate: total > 0 ? (wins / total * 100).toFixed(1) : 0,
    total_profit: totalProfit.toFixed(2)
  }
}
```

### Python

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Get today's parlays
response = supabase.table('nhl_sgp_parlays') \
    .select('*, nhl_sgp_legs(*)') \
    .eq('game_date', '2025-12-14') \
    .eq('parlay_type', 'primary') \
    .execute()

parlays = response.data
```

---

## Real-time Subscriptions

### Subscribe to New Parlays

```typescript
const subscription = supabase
  .channel('nhl-sgp-updates')
  .on(
    'postgres_changes',
    {
      event: 'INSERT',
      schema: 'public',
      table: 'nhl_sgp_parlays'
    },
    (payload) => {
      console.log('New parlay:', payload.new)
      // Trigger UI refresh
    }
  )
  .subscribe()

// Cleanup
subscription.unsubscribe()
```

### Subscribe to Settlements

```typescript
const settlementSub = supabase
  .channel('nhl-sgp-settlements')
  .on(
    'postgres_changes',
    {
      event: 'INSERT',
      schema: 'public',
      table: 'nhl_sgp_settlements'
    },
    (payload) => {
      console.log('Parlay settled:', payload.new)
      // Update UI with result
    }
  )
  .subscribe()
```

---

## Frontend Components

### Recommended Component Structure

```
components/
  nhl-sgp/
    ParlayCard.tsx          # Single parlay display
    ParlayList.tsx          # List of parlays for a date
    LegRow.tsx              # Single leg within parlay
    SignalBreakdown.tsx     # Signal visualization
    PerformanceStats.tsx    # Win rate, profit summary
    SettlementBadge.tsx     # WIN/LOSS/PENDING badge
```

### ParlayCard Props

```typescript
interface ParlayCardProps {
  parlay: {
    id: string
    parlay_type: string
    game_date: string
    home_team: string
    away_team: string
    combined_odds: number
    implied_probability: number
    thesis: string
    nhl_sgp_legs: Leg[]
    nhl_sgp_settlements?: Settlement[]
  }
  showSignals?: boolean
  onLegClick?: (leg: Leg) => void
}
```

### Display Formatting

```typescript
// Format odds display
function formatOdds(odds: number): string {
  return odds > 0 ? `+${odds}` : `${odds}`
}

// Format edge percentage
function formatEdge(edge: number): string {
  return `+${edge.toFixed(1)}%`
}

// Format implied probability
function formatProb(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`
}

// Get result color
function getResultColor(result: string | null): string {
  switch (result) {
    case 'WIN': return 'text-green-600'
    case 'LOSS': return 'text-red-600'
    case 'PUSH': return 'text-yellow-600'
    case 'VOID': return 'text-gray-400'
    default: return 'text-gray-600'
  }
}
```

---

## Error Handling

### Common Errors

| Status | Message | Resolution |
|--------|---------|------------|
| 401 | Invalid API key | Check `apikey` header |
| 404 | No rows found | Query returned empty - valid |
| 400 | Invalid filter | Check PostgREST filter syntax |

### Error Response Structure

```json
{
  "message": "JSON object requested, multiple (or no) rows returned",
  "code": "PGRST116",
  "details": null,
  "hint": null
}
```

### Frontend Error Handling

```typescript
async function fetchParlays() {
  try {
    const { data, error } = await supabase
      .from('nhl_sgp_parlays')
      .select('*, nhl_sgp_legs(*)')
      .eq('game_date', today)

    if (error) {
      console.error('Supabase error:', error.message)
      return { error: 'Failed to load parlays' }
    }

    return { data }
  } catch (e) {
    console.error('Network error:', e)
    return { error: 'Network error - please try again' }
  }
}
```

---

## Data Refresh Schedule

| Time (ET) | Event | Tables Updated |
|-----------|-------|----------------|
| 9:00 AM | Settlement | `nhl_sgp_legs.result`, `nhl_sgp_settlements` |
| 9:00 AM | Generation | `nhl_sgp_parlays`, `nhl_sgp_legs` |

### Recommended Frontend Caching

- **Parlays**: Cache for 5 minutes during non-game hours
- **Settlements**: Cache for 1 hour (updates once daily)
- **Performance**: Cache for 15 minutes

---

## Stat Types Reference

| Code | Display Name | Market Key |
|------|-------------|------------|
| `points` | Points | `player_points` |
| `shots_on_goal` | Shots on Goal | `player_shots_on_goal` |

*Note: Only these 2 markets are currently validated. Additional markets may be added after validation.*

---

## Team Abbreviations

| Abbrev | Team Name |
|--------|-----------|
| ANA | Anaheim Ducks |
| BOS | Boston Bruins |
| BUF | Buffalo Sabres |
| CGY | Calgary Flames |
| CAR | Carolina Hurricanes |
| CHI | Chicago Blackhawks |
| COL | Colorado Avalanche |
| CBJ | Columbus Blue Jackets |
| DAL | Dallas Stars |
| DET | Detroit Red Wings |
| EDM | Edmonton Oilers |
| FLA | Florida Panthers |
| LAK | Los Angeles Kings |
| MIN | Minnesota Wild |
| MTL | Montreal Canadiens |
| NSH | Nashville Predators |
| NJD | New Jersey Devils |
| NYI | New York Islanders |
| NYR | New York Rangers |
| OTT | Ottawa Senators |
| PHI | Philadelphia Flyers |
| PIT | Pittsburgh Penguins |
| SJS | San Jose Sharks |
| SEA | Seattle Kraken |
| STL | St. Louis Blues |
| TBL | Tampa Bay Lightning |
| TOR | Toronto Maple Leafs |
| UTA | Utah Hockey Club |
| VAN | Vancouver Canucks |
| VGK | Vegas Golden Knights |
| WSH | Washington Capitals |
| WPG | Winnipeg Jets |

---

*Document Version: 1.0*
*Last Updated: December 2025*
