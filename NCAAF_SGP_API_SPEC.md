# SGP Engine API Specification

**Version:** 1.0
**Last Updated:** December 13, 2025
**Base URL:** `https://[project-id].supabase.co/rest/v1`

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Database Tables](#database-tables)
4. [API Endpoints](#api-endpoints)
5. [Data Models](#data-models)
6. [Query Examples](#query-examples)
7. [Frontend Integration](#frontend-integration)
8. [WebSocket Subscriptions](#websocket-subscriptions)

---

## Overview

The SGP (Same Game Parlay) Engine generates optimized multi-leg parlay recommendations for NCAAF games using a 6-signal analytical framework. Data is stored in Supabase and accessible via REST API or real-time subscriptions.

### Key Features

- **Daily Parlay Generation**: Automatic generation for each game day
- **6-Signal Framework**: Line value, trend, usage, matchup, environment, correlation, weather
- **Multi-Leg Optimization**: 2-4 legs per parlay with correlation checking
- **Settlement Tracking**: Win/loss tracking with actual values
- **Real-time Updates**: Supabase real-time subscriptions available

### Signal Weights

| Signal | Weight | Description |
|--------|--------|-------------|
| Line Value | 35% | Season average vs prop line comparison |
| Environment | 15% | Game script, venue, spread, total |
| Trend | 15% | Last 5 games vs season average |
| Matchup | 15% | Opponent defensive quality (SP+ ranking) |
| Usage | 10% | Volume/opportunity changes |
| Correlation | 5% | Prop correlation with game outcome |
| Weather | 5% | Wind/temperature impact (outdoor venues) |

---

## Authentication

### Read Access (Public)

```bash
# Anonymous read access with anon key
curl -X GET \
  'https://[project-id].supabase.co/rest/v1/ncaaf_sgp_parlays' \
  -H 'apikey: [anon-key]' \
  -H 'Authorization: Bearer [anon-key]'
```

### Write Access (Service Role)

```bash
# Service role for write operations
curl -X POST \
  'https://[project-id].supabase.co/rest/v1/ncaaf_sgp_parlays' \
  -H 'apikey: [service-role-key]' \
  -H 'Authorization: Bearer [service-role-key]' \
  -H 'Content-Type: application/json'
```

### Environment Variables

```bash
SUPABASE_URL=https://[project-id].supabase.co
SUPABASE_ANON_KEY=[anon-key]        # Read-only
SUPABASE_KEY=[service-role-key]     # Full access
```

---

## Database Tables

### `ncaaf_sgp_parlays`

Parent table storing parlay recommendations.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `a1b2c3d4-...` |
| `parlay_type` | VARCHAR(50) | Parlay category | `primary`, `theme_stack`, `value_play` |
| `game_id` | VARCHAR(100) | Unique game identifier | `2025_16_Army_Navy` |
| `game_date` | DATE | Game date | `2025-12-13` |
| `home_team` | VARCHAR(50) | Home team name | `Navy` |
| `away_team` | VARCHAR(50) | Away team name | `Army` |
| `season_type` | VARCHAR(20) | Season phase | `regular`, `postseason` |
| `game_slot` | VARCHAR(20) | Time slot | `SATURDAY`, `BOWL`, `PLAYOFF` |
| `total_legs` | INTEGER | Number of legs | `4` |
| `combined_odds` | INTEGER | American odds | `1266` |
| `implied_probability` | DECIMAL(5,4) | Win probability | `0.0732` |
| `thesis` | TEXT | Narrative explanation | `Low total suggests defensive...` |
| `season` | INTEGER | Season year | `2025` |
| `week` | INTEGER | Week number | `16` |
| `created_at` | TIMESTAMP | Creation time | `2025-12-13T10:15:00Z` |
| `updated_at` | TIMESTAMP | Last update | `2025-12-13T10:15:00Z` |

**Unique Constraint:** `(season, week, season_type, parlay_type, game_id)`

---

### `ncaaf_sgp_legs`

Individual legs within each parlay.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `b2c3d4e5-...` |
| `parlay_id` | UUID | FK to parlays | `a1b2c3d4-...` |
| `leg_number` | INTEGER | Order in parlay | `1`, `2`, `3` |
| `player_name` | VARCHAR(100) | Player display name | `Eli Heidenreich` |
| `team` | VARCHAR(50) | Player's team | `Navy` |
| `position` | VARCHAR(10) | Position code | `WR`, `RB`, `QB`, `TE` |
| `stat_type` | VARCHAR(50) | Prop type | `pass_yds`, `rush_yds`, `rec_yds`, `receptions`, `attd` |
| `line` | DECIMAL(6,1) | Prop line | `44.5` |
| `direction` | VARCHAR(10) | Over/under | `over`, `under` |
| `odds` | INTEGER | American odds | `104`, `-113` |
| `edge_pct` | DECIMAL(5,2) | Projected edge | `12.08` |
| `confidence` | DECIMAL(3,2) | Confidence score | `0.82` |
| `model_probability` | DECIMAL(5,4) | Model win prob | `0.6110` |
| `market_probability` | DECIMAL(5,4) | Implied prob | `0.4902` |
| `primary_reason` | TEXT | Main evidence | `Season avg 73.2 is 64% ABOVE line 44.5` |
| `supporting_reasons` | JSONB | Additional reasons | `["Opponent defense #89"]` |
| `risk_factors` | JSONB | Risk warnings | `["High wind expected"]` |
| `signals` | JSONB | Full signal breakdown | See Signal Object |
| `actual_value` | DECIMAL(6,1) | Post-game actual | `82.0` |
| `result` | VARCHAR(10) | Settlement result | `WIN`, `LOSS`, `PUSH`, `VOID` |
| `created_at` | TIMESTAMP | Creation time | `2025-12-13T10:15:00Z` |

**Foreign Key:** `parlay_id` references `ncaaf_sgp_parlays(id)`

---

### `ncaaf_sgp_settlements`

Settlement records for completed parlays.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | UUID | Primary key | `c3d4e5f6-...` |
| `parlay_id` | UUID | FK to parlays | `a1b2c3d4-...` |
| `legs_hit` | INTEGER | Legs that hit | `3` |
| `total_legs` | INTEGER | Total scoreable legs | `4` |
| `result` | VARCHAR(10) | Parlay result | `WIN`, `LOSS`, `VOID` |
| `settled_at` | TIMESTAMP | Settlement time | `2025-12-14T08:00:00Z` |
| `notes` | TEXT | Settlement notes | `Settled 2025-12-14T08:00:00` |

---

## API Endpoints

### Get Today's Parlays

```http
GET /ncaaf_sgp_parlays?game_date=eq.2025-12-13&select=*,ncaaf_sgp_legs(*)
```

**Response:**
```json
[
  {
    "id": "a1b2c3d4-1111-4000-8000-000000000001",
    "parlay_type": "primary",
    "game_id": "2025_16_Army_Navy",
    "game_date": "2025-12-13",
    "home_team": "Navy",
    "away_team": "Army",
    "total_legs": 4,
    "combined_odds": 1266,
    "implied_probability": 0.0732,
    "thesis": "Low total (38.5) suggests defensive battle...",
    "ncaaf_sgp_legs": [
      {
        "leg_number": 1,
        "player_name": "Eli Heidenreich",
        "stat_type": "rec_yds",
        "line": 44.5,
        "direction": "over",
        "odds": 104,
        "edge_pct": 12.08,
        "confidence": 0.82,
        "primary_reason": "Season avg 73.2 is 64% ABOVE line 44.5"
      }
    ]
  }
]
```

### Get Parlays by Week

```http
GET /ncaaf_sgp_parlays?season=eq.2025&week=eq.16&select=*,ncaaf_sgp_legs(*)
```

### Get Parlays by Game

```http
GET /ncaaf_sgp_parlays?game_id=eq.2025_16_Army_Navy&select=*,ncaaf_sgp_legs(*)
```

### Get Primary Parlays Only

```http
GET /ncaaf_sgp_parlays?parlay_type=eq.primary&select=*,ncaaf_sgp_legs(*)&order=game_date.desc
```

### Get Settled Parlays

```http
GET /ncaaf_sgp_parlays?select=*,ncaaf_sgp_legs(*),ncaaf_sgp_settlements(*)
  &ncaaf_sgp_settlements.result=not.is.null
```

### Get High-Edge Legs

```http
GET /ncaaf_sgp_legs?edge_pct=gte.10&order=edge_pct.desc&limit=20
```

---

## Data Models

### Signal Object

The `signals` JSONB column contains the full signal breakdown:

```json
{
  "line_value": {
    "evidence": "Season avg 73.2 is 64% ABOVE line 44.5 (strong edge)",
    "strength": 0.967,
    "confidence": 0.9
  },
  "trend": {
    "evidence": "L5 avg 80.5 vs season 73.2 (UP 10.0%)",
    "strength": 0.1,
    "confidence": 0.85
  },
  "usage": {
    "evidence": "Targets STABLE: 3.6/gm L5 vs 3.6 season",
    "strength": 0.0,
    "confidence": 0.95
  },
  "matchup": {
    "evidence": "Opponent defense rank #54 (average)",
    "strength": -0.203,
    "confidence": 0.85
  },
  "environment": {
    "evidence": "Low total (38.5) = defensive game",
    "strength": -0.1,
    "confidence": 0.6
  },
  "correlation": {
    "evidence": "Low Total correlates -20% with rec_yds",
    "strength": -0.06,
    "confidence": 0.66
  },
  "weather": {
    "evidence": "Good weather conditions (45F, 8 mph wind)",
    "strength": 0.0,
    "confidence": 0.8
  }
}
```

### Parlay Types

| Type | Description | Typical Legs |
|------|-------------|--------------|
| `primary` | Best overall edge parlay | 3-4 |
| `theme_stack` | Correlated theme (e.g., ground game) | 2-3 |
| `value_play` | High-value single or double | 1-2 |

### Stat Types

| Code | Description | Example Line |
|------|-------------|--------------|
| `pass_yds` | Passing yards | 225.5 |
| `rush_yds` | Rushing yards | 55.5 |
| `rec_yds` | Receiving yards | 44.5 |
| `receptions` | Receptions | 4.5 |
| `attd` | Anytime touchdown | null (yes/no) |
| `pass_tds` | Passing touchdowns | 1.5 |

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

### JavaScript/TypeScript (Supabase Client)

```typescript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

// Get today's parlays with legs
const { data: parlays, error } = await supabase
  .from('ncaaf_sgp_parlays')
  .select(`
    *,
    ncaaf_sgp_legs (*)
  `)
  .eq('game_date', '2025-12-13')
  .order('combined_odds', { ascending: false })

// Get all primary parlays for bowl season
const { data: bowlParlays } = await supabase
  .from('ncaaf_sgp_parlays')
  .select('*, ncaaf_sgp_legs(*)')
  .eq('parlay_type', 'primary')
  .eq('season_type', 'postseason')
  .gte('game_date', '2025-12-14')

// Get high-confidence legs
const { data: topLegs } = await supabase
  .from('ncaaf_sgp_legs')
  .select('*, ncaaf_sgp_parlays!inner(game_date, home_team, away_team)')
  .gte('confidence', 0.8)
  .gte('edge_pct', 8)
  .order('edge_pct', { ascending: false })
  .limit(10)

// Get settled parlays with results
const { data: settledParlays } = await supabase
  .from('ncaaf_sgp_parlays')
  .select(`
    *,
    ncaaf_sgp_legs (*),
    ncaaf_sgp_settlements (*)
  `)
  .not('ncaaf_sgp_settlements', 'is', null)
  .order('game_date', { ascending: false })
```

### Python (Supabase Client)

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get today's parlays
response = supabase.table('ncaaf_sgp_parlays') \
    .select('*, ncaaf_sgp_legs(*)') \
    .eq('game_date', '2025-12-13') \
    .execute()

parlays = response.data

# Get performance summary
response = supabase.rpc('get_sgp_performance', {
    'start_date': '2025-12-01',
    'end_date': '2025-12-31'
}).execute()
```

### REST API (cURL)

```bash
# Get parlays for a specific game
curl -X GET \
  'https://[project-id].supabase.co/rest/v1/ncaaf_sgp_parlays?game_id=eq.2025_16_Army_Navy&select=*,ncaaf_sgp_legs(*)' \
  -H 'apikey: [anon-key]' \
  -H 'Authorization: Bearer [anon-key]'

# Get top edges across all games
curl -X GET \
  'https://[project-id].supabase.co/rest/v1/ncaaf_sgp_legs?edge_pct=gte.10&order=edge_pct.desc&limit=10' \
  -H 'apikey: [anon-key]'
```

---

## Frontend Integration

### React Component Example

```tsx
import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'

interface SGPParlay {
  id: string
  parlay_type: string
  game_id: string
  home_team: string
  away_team: string
  combined_odds: number
  thesis: string
  ncaaf_sgp_legs: SGPLeg[]
}

interface SGPLeg {
  leg_number: number
  player_name: string
  stat_type: string
  line: number
  direction: string
  edge_pct: number
  confidence: number
  primary_reason: string
}

export function TodaysParlays() {
  const [parlays, setParlays] = useState<SGPParlay[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchParlays() {
      const today = new Date().toISOString().split('T')[0]

      const { data, error } = await supabase
        .from('ncaaf_sgp_parlays')
        .select('*, ncaaf_sgp_legs(*)')
        .eq('game_date', today)
        .eq('parlay_type', 'primary')
        .order('combined_odds', { ascending: false })

      if (data) setParlays(data)
      setLoading(false)
    }

    fetchParlays()
  }, [])

  if (loading) return <div>Loading...</div>

  return (
    <div className="space-y-6">
      {parlays.map((parlay) => (
        <div key={parlay.id} className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-bold">
              {parlay.away_team} @ {parlay.home_team}
            </h3>
            <span className="text-green-600 font-bold">
              +{parlay.combined_odds}
            </span>
          </div>

          <p className="text-gray-600 mb-4">{parlay.thesis}</p>

          <div className="space-y-3">
            {parlay.ncaaf_sgp_legs
              .sort((a, b) => a.leg_number - b.leg_number)
              .map((leg) => (
                <div key={leg.leg_number} className="border-l-4 border-blue-500 pl-4">
                  <div className="font-medium">
                    {leg.player_name} {leg.stat_type.replace('_', ' ')} {leg.direction.toUpperCase()} {leg.line}
                  </div>
                  <div className="text-sm text-gray-500">
                    Edge: +{leg.edge_pct.toFixed(1)}% | Confidence: {(leg.confidence * 100).toFixed(0)}%
                  </div>
                  <div className="text-sm text-gray-400">
                    {leg.primary_reason}
                  </div>
                </div>
              ))}
          </div>
        </div>
      ))}
    </div>
  )
}
```

### API Response Transformation

```typescript
// Transform for display
function formatParlay(parlay: SGPParlay) {
  return {
    id: parlay.id,
    matchup: `${parlay.away_team} @ ${parlay.home_team}`,
    odds: parlay.combined_odds > 0 ? `+${parlay.combined_odds}` : parlay.combined_odds,
    impliedProb: `${(parlay.implied_probability * 100).toFixed(1)}%`,
    thesis: parlay.thesis,
    legs: parlay.ncaaf_sgp_legs.map(leg => ({
      pick: `${leg.player_name} ${leg.stat_type.replace('_', ' ')} ${leg.direction.toUpperCase()} ${leg.line || 'ATTD'}`,
      edge: `+${leg.edge_pct.toFixed(1)}%`,
      confidence: `${(leg.confidence * 100).toFixed(0)}%`,
      reason: leg.primary_reason,
      signals: leg.signals
    }))
  }
}
```

---

## WebSocket Subscriptions

### Real-time Updates

```typescript
// Subscribe to new parlays
const subscription = supabase
  .channel('sgp-updates')
  .on(
    'postgres_changes',
    {
      event: 'INSERT',
      schema: 'public',
      table: 'ncaaf_sgp_parlays'
    },
    (payload) => {
      console.log('New parlay:', payload.new)
      // Refetch or update local state
    }
  )
  .on(
    'postgres_changes',
    {
      event: 'UPDATE',
      schema: 'public',
      table: 'ncaaf_sgp_legs',
      filter: 'result=neq.null'
    },
    (payload) => {
      console.log('Leg settled:', payload.new)
      // Update UI with settlement result
    }
  )
  .subscribe()

// Cleanup
subscription.unsubscribe()
```

---

## Data Refresh Schedule

| Time (ET) | Event | Tables Updated |
|-----------|-------|----------------|
| 9:00 AM | SGP Generation | `ncaaf_sgp_parlays`, `ncaaf_sgp_legs` |
| 9:00 AM | Settlement | `ncaaf_sgp_legs` (result), `ncaaf_sgp_settlements` |
| 3:00 PM | SGP Update | `ncaaf_sgp_parlays`, `ncaaf_sgp_legs` (latest odds) |

---

## Error Handling

### Common Errors

| Status | Message | Resolution |
|--------|---------|------------|
| 401 | Invalid API key | Check `apikey` header |
| 404 | No rows found | Query returned empty - valid |
| 400 | Invalid filter | Check PostgREST filter syntax |
| 500 | Server error | Retry or check Supabase status |

### Response Structure

```json
{
  "data": [...],
  "error": null,
  "count": 10,
  "status": 200,
  "statusText": "OK"
}
```

---

## Performance Considerations

1. **Use `select` to limit columns** - Don't fetch full `signals` JSONB if not needed
2. **Paginate large result sets** - Use `range(0, 49)` for pagination
3. **Cache static data** - Parlays don't change after generation (except settlement)
4. **Subscribe selectively** - Only subscribe to tables/filters you need

---

## Changelog

### v1.0 (December 13, 2025)
- Initial SGP Engine release
- 6-signal framework implementation
- Bowl season automation
- Settlement tracking
