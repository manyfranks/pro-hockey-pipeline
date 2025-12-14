# NHL SGP Engine Design Document

**Version:** 1.0 (POC)
**Last Updated:** December 13, 2025
**Status:** Proof of Concept

---

## Philosophy

### Market-First Approach

The SGP engine is fundamentally different from a prediction model. Instead of asking "Will this player score?", we ask "**Where does our data disagree with the market?**"

This is a critical distinction:

| Prediction Model | Edge Detection Model |
|------------------|---------------------|
| Outputs: "Player X will score 1.2 points" | Outputs: "Market implies 45% over, we estimate 55%" |
| Evaluated by: Prediction accuracy | Evaluated by: Profitability |
| Optimizes for: Correct predictions | Optimizes for: Edge identification |

### The Problem with Predictions

The NHL pipeline predicts which players are most likely to score points. But **markets already know this**. A player ranked #1 in our pipeline will have low odds (high implied probability) on their props.

**Example:**
- Pipeline says: Connor McDavid top-ranked scorer
- Market says: McDavid 0.5 points at -250 (71% implied)
- Our model: 75% probability
- Edge: 75% - 71% = **4% edge** (below threshold)

vs.

- Pipeline says: 4th liner with hot streak
- Market says: Player X 0.5 points at +100 (50% implied)
- Our model: 58% probability (recent form + weak goalie)
- Edge: 58% - 50% = **8% edge** (actionable)

---

## Architecture

### Strategic Blend (Validated Decision)

After backtesting, we made a deliberate architectural decision: **Blend, don't pivot.**

Per MULTI_LEAGUE_ARCHITECTURE.md, the SGP engine should be independent with pipeline as "supplemental." However, our backtest proved that pipeline context provides **significant alpha**:

| Segment | Hit Rate | Delta |
|---------|----------|-------|
| Scoreable players | 61.4% | +22 pts |
| Non-scoreable | 39.1% | baseline |
| Pipeline rank 1-25 | 71-75% | +20 pts |

**The pipeline context IS the edge.** Removing it for architectural purity would destroy validated signal.

### Dual-Path Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     NHL SGP ENGINE                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PATH A: Points/Assists (VALIDATED - 62.5% hit rate)            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Odds API → Pipeline Enrichment → 6 Signals → Edge Calc     │ │
│  │            ↑                                                │ │
│  │            │ is_scoreable, rank, line_number, pp_unit       │ │
│  │            │ goalie matchup, recent form (DailyFaceoff)     │ │
│  │            │                                                │ │
│  │            └── THIS IS OUR EDGE - PRESERVE IT               │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  PATH B: SOG/Saves/Blocks (EXPLORATORY - unvalidated)           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Odds API → NHL API Direct → 6 Signals → Edge Calc          │ │
│  │            ↑                                                │ │
│  │            │ Query on-demand, no pipeline dependency        │ │
│  │            │ Validate before investing in pipeline build    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Why Not "Pure" Architecture?

| Data Point | NHL API Direct | Pipeline | Winner |
|------------|----------------|----------|--------|
| Season stats | Yes | Yes | Tie |
| Line deployment | **No** | Yes (DailyFaceoff) | **Pipeline** |
| PP unit assignment | **No** | Yes (DailyFaceoff) | **Pipeline** |
| Goalie confirmation | **No** | Yes (DailyFaceoff) | **Pipeline** |
| "Scoreable" composite | **No** | Yes | **Pipeline** |
| SOG/Blocks/Saves | Yes | **No** | **NHL API** |

The pipeline provides **derived intelligence** (line combos, PP units, scoreable filter) that raw NHL API doesn't offer. This derived intelligence drives our 62.5% hit rate.

### Component Overview

```
nhl_sgp_engine/
├── config/
│   ├── settings.py          # Thresholds, weights, API config
│   └── markets.py            # Odds API market definitions
├── providers/
│   ├── odds_api_client.py    # Odds API integration
│   ├── pipeline_adapter.py   # NHL pipeline bridge (Path A)
│   └── nhl_api_adapter.py    # Direct NHL API (Path B - future)
├── signals/
│   ├── base.py               # BaseSignal, SignalResult, PropContext
│   ├── line_value_signal.py  # Season avg vs prop line
│   ├── trend_signal.py       # Recent form vs season
│   ├── usage_signal.py       # TOI, PP, line changes
│   ├── matchup_signal.py     # Goalie quality
│   ├── environment_signal.py # B2B, home/away
│   └── correlation_signal.py # Game total impact
├── edge_detection/
│   └── edge_calculator.py    # Signal combination, edge calculation
├── database/
│   └── sgp_db_manager.py     # PostgreSQL operations
├── backtesting/
│   └── backtest_engine.py    # Historical validation
└── scripts/
    ├── run_enriched_backtest.py
    ├── run_points_only_backtest.py
    └── fetch_odds_for_predictions.py
```

### Data Flow (Path A - Validated)

```
1. FETCH
   Odds API → Player props with prices (points, assists, goals)
   Pipeline → Rich context from nhl_daily_predictions

2. ENRICH
   PropContext = Pipeline data + Odds data
   Key fields: is_scoreable, rank, line_number, pp_unit, goalie matchup

3. CALCULATE
   6 Signals → Weighted combination → Model probability

4. COMPARE
   Model probability - Market implied probability = Edge %

5. FILTER
   stat_type = 'points' AND
   edge_pct BETWEEN 5.0 AND 8.0 AND
   is_scoreable = true AND
   pipeline_rank <= 50
```

---

## Signal Framework

### Signal Weights

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Line Value | 35% | Season average vs line is most predictive for points |
| Trend | 15% | Recent form captures momentum |
| Matchup | 15% | Goalie quality matters for scoring |
| Environment | 15% | Situational factors (B2B, rest) |
| Usage | 10% | TOI/PP changes affect opportunity |
| Correlation | 10% | Game script impacts scoring |

### Signal Specifications

#### 1. Line Value Signal (35%)

**Purpose:** Compare player's season average to the prop line.

**Formula:**
```
gap = (season_avg - line) / line
strength = clamp(gap / 0.5, -1, 1)
```

**Example:**
- Season avg: 0.85 PPG
- Line: 0.5
- Gap: (0.85 - 0.5) / 0.5 = 0.70 (70% above line)
- Strength: 0.70 / 0.5 = 1.0 (max positive)

**Confidence Modifiers:**
- Games played < 15: -0.15 confidence
- Consistent performer (low variance): +0.10 confidence

---

#### 2. Trend Signal (15%)

**Purpose:** Detect hot/cold streaks not reflected in season averages.

**Formula:**
```
pct_change = (recent_ppg - season_avg) / season_avg
strength = clamp(pct_change / 0.3, -1, 1)
```

**Example:**
- Recent PPG (L10): 1.1
- Season PPG: 0.85
- Change: (1.1 - 0.85) / 0.85 = 29.4%
- Strength: 0.294 / 0.3 = 0.98

**Confidence Modifiers:**
- Point streak >= 5 games: +0.15 confidence
- Point streak >= 3 games: +0.08 confidence
- Recent games < 5: -0.20 confidence

---

#### 3. Usage Signal (10%)

**Purpose:** Detect changes in ice time and power play deployment.

**Inputs:**
- `line_number`: Even-strength line (1-4)
- `pp_unit`: Power play unit (1, 2, or null)
- `avg_toi_minutes`: Recent average TOI

**Logic:**
```
if top_line (1-2) and PP1: strength = +0.3
if top_line only: strength = +0.15
if bottom_6 and no_PP: strength = -0.2
```

**Confidence:** 0.70 base (DailyFaceoff data can be stale)

---

#### 4. Matchup Signal (15%)

**Purpose:** Factor in opposing goalie quality.

**Inputs:**
- `opposing_goalie_sv_pct`: Save percentage
- `opposing_goalie_gaa`: Goals against average
- `goalie_confirmed`: Whether starter is confirmed

**Formula:**
```
# Lower SV% = weaker goalie = more scoring
# League avg ~0.905
sv_deviation = 0.905 - goalie_sv_pct
strength = sv_deviation * 10  # 0.895 SV% = +0.1, 0.915 = -0.1
```

**Confidence Modifiers:**
- Goalie confirmed: 0.80 base
- Goalie not confirmed: 0.50 base

---

#### 5. Environment Signal (15%)

**Purpose:** Capture situational factors affecting performance.

**Inputs:**
- `is_home`: Home/away
- `is_b2b`: Back-to-back game
- `days_rest`: Days since last game

**Logic:**
```
strength = 0.0
if is_home: strength += 0.05
if is_b2b: strength -= 0.15
if days_rest >= 3: strength += 0.05
```

**Confidence:** 0.75 base

---

#### 6. Correlation Signal (10%)

**Purpose:** Adjust expectations based on expected game script.

**Inputs:**
- `game_total`: Over/under for game
- `spread`: Point spread

**Logic:**
```
# High-total games = more scoring opportunities
if game_total >= 6.5: strength = +0.15
elif game_total <= 5.5: strength = -0.10

# Large favorites may rest stars late
if abs(spread) >= 2.0: confidence -= 0.15
```

**Confidence:** 0.65 base (game lines not always available)

---

## Edge Calculation

### Model Probability

Signals are combined using weighted average, then converted to probability:

```python
# Combine signals
weighted_signal = sum(strength * weight * confidence) / sum(weight * confidence)

# Convert to probability using logistic function
# weighted_signal of 0 -> 50%
# weighted_signal of +1 -> ~73%
# weighted_signal of -1 -> ~27%

base_logit = log(0.5 / 0.5)  # 0
adjusted_logit = base_logit + (weighted_signal * 1.5)
model_probability = 1 / (1 + exp(-adjusted_logit))
```

### Market Probability

American odds converted to implied probability:

```python
def american_to_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)  # +150 -> 40%
    else:
        return abs(odds) / (abs(odds) + 100)  # -150 -> 60%
```

### Edge Percentage

```python
edge_pct = (model_probability - market_probability) * 100

# Example:
# Model: 58%
# Market: 50%
# Edge: 8%
```

### Direction Selection

The engine recommends the side with the highest edge:

```python
over_edge = model_prob_over - implied_prob_over
under_edge = model_prob_under - implied_prob_under

if over_edge >= under_edge:
    direction = 'over'
    edge = over_edge
else:
    direction = 'under'
    edge = under_edge
```

---

## Thresholds

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| MIN_EDGE_PCT | 5.0% | Minimum actionable edge |
| HIGH_EDGE_PCT | 8.0% | High-value threshold |
| ELITE_EDGE_PCT | 12.0% | Elite edge (rare) |
| MIN_CONFIDENCE | 0.60 | Minimum signal confidence |
| MAX_LEGS_PER_PARLAY | 4 | Parlay construction |
| MIN_LEGS_PER_PARLAY | 2 | Parlay construction |

---

## Parlay Construction (Future)

### Primary Parlay

- Select top 3-4 edges from a single game
- Check for negative correlation (same outcome dependence)
- Generate thesis narrative

### Theme Stack

- Find correlated edges (e.g., multiple players benefiting from weak goalie)
- 2-3 legs with thematic connection

### Value Play

- Single high-confidence, high-edge prop
- Or 2-leg combination with very high expected value

---

## Settlement

### Automated Settlement

The engine settles props using pipeline outcome data:

```python
# From nhl_daily_predictions
actual_points = pipeline.get_actual_outcome(player_name, 'points', game_date)

# Determine result
if direction == 'over':
    hit = actual_points > line
else:
    hit = actual_points <= line
```

### Push Handling

```python
if actual_points == line:
    result = 'PUSH'  # Bet returned
```

---

## Future Enhancements

### Phase 2: Shot-Based Signals

For goals props validation:
- Expected goals (xG) data
- Shot attempt rates
- Shooting percentage trends

### Phase 3: Real-Time Updates

- Live odds monitoring
- Injury/scratch detection
- Goalie change alerts

### Phase 4: Parlay Optimization

- Correlation matrix between props
- Kelly criterion for sizing
- Multi-book arbitrage detection

---

*Document Version: 1.0*
*Last Updated: December 13, 2025*
