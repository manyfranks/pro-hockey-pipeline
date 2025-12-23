# NHL Pipeline Strategic Roadmap
**Generated**: December 22, 2025
**Based on**: 48,000+ prop backtest analysis (Nov-Dec 2025)

---

## Executive Summary

The backtest audit revealed several high-impact optimization opportunities. This document prioritizes them by expected ROI and implementation complexity.

---

## 1. IMMEDIATE TODOS (Production Ready)

### Completed This Session
- [x] Saves settlement fix (goalie context builder)
- [x] Assists threshold: 15% → 5% (+13.7% edge improvement)
- [x] Shots threshold: 15% → 10% (+9.6% edge improvement)
- [x] Database migration (`is_star_leg` column)
- [x] Full backtest audit (all 5 markets validated)

### Still Required Before Production
- [ ] **Verify tiered parlay system works** - MIN_LEGS=2, MAX=3, star player allows 4th
- [ ] **Test regression penalty system** - Players with PPG > 2.0 should show flags
- [ ] **Smoke test daily pipeline** - Run for tomorrow's games, verify output format

---

## 2. SIGNAL WEIGHT REBALANCING (High Priority)

### Current vs Recommended Weights

Based on 48,000+ prop backtest, signal predictive values are **inverted from current weights**:

| Signal | Current Weight | Avg Predictive Value | Recommended Weight | Change |
|--------|----------------|---------------------|-------------------|--------|
| environment | 0.24 | 34.1%* | 0.20 | ⬇️ -0.04 |
| matchup | 0.10 | 20.7% | 0.25 | ⬆️ +0.15 |
| usage | 0.19 | 4.2% | 0.12 | ⬇️ -0.07 |
| line_value | 0.15 | 5.5% | 0.12 | ⬇️ -0.03 |
| correlation | 0.04 | 1.2% | 0.02 | ⬇️ -0.02 |
| trend | 0.04 | 1.5% | 0.02 | ⬇️ -0.02 |
| shot_quality | 0.08 | N/A | 0.10 | ⬆️ +0.02 |
| goalie_saves | 0.08 | 52.6%** | 0.10 | ⬆️ +0.02 |
| game_totals | 0.08 | N/A | 0.07 | ⬇️ -0.01 |

**Notes:**
- *Environment bug FIXED Dec 22 - was showing 0% positive due to threshold issue
- **Goalie saves is market-specific, not a cross-market signal

### Environment Signal Bug (FIXED Dec 22, 2025)

```
BEFORE FIX:
  assists         | Pos:  0.0% (n=    0) | Neg: 48.4% (n= 1499)

Root cause: Max positive output was +0.05 (home ice), but threshold for
"positive" was > 0.05. So 0.05 was classified as NEUTRAL, not positive.

AFTER FIX (scaled up adjustments):
  Home ice:      +0.05 → +0.20 (now classified as POSITIVE)
  Away:          -0.03 → -0.10 (now classified as NEGATIVE)
  B2B + home:    -0.25 → -0.70
  B2B + away:    -0.33 → -1.00
  Well-rested:   +0.10 → +0.30
```

**Status**: ✅ FIXED - Environment signal now uses full range like other signals.

---

## 3. LINEMATE STACK-WITH FEATURE (Medium Priority)

### Concept
When predicting Connor McDavid has a big night, his linemates (Draisaitl, Hyman) should also see uplifted predictions. This correlation can be exploited for both:
1. Individual prop predictions
2. SGP parlay construction (positive correlation = reduced vig)

### Implementation Requirements

#### A. Line Deployment Data Sources

| Source | Data Type | Update Frequency | Integration |
|--------|-----------|------------------|-------------|
| NHL Shift Charts API | Who plays with whom | Post-game | `api.nhle.com/stats/rest/en/shiftcharts` |
| DailyFaceoff.com | Projected lines | Daily | Web scrape |
| LeftWingLock.com | Line combinations | Daily | Web scrape |
| TOI inference | Historical TOI patterns | Pre-game | Already implemented |

#### B. Correlation Analysis

```python
# Pseudocode for linemate correlation
def calculate_linemate_boost(player_a_prediction, player_b_stats):
    """
    When player A is predicted high, boost player B if they're linemates.

    Historical analysis needed:
    - When McDavid scores, how often does Draisaitl score? (correlation coefficient)
    - When Crosby gets 2+ points, what's Malkin's hit rate?
    """
    if are_linemates(player_a, player_b):
        correlation = get_historical_correlation(player_a, player_b, stat_type)
        boost = player_a_prediction.edge_pct * correlation * 0.5
        return boost
    return 0
```

#### C. Database Schema Addition

```sql
CREATE TABLE nhl_line_combinations (
    id SERIAL PRIMARY KEY,
    game_date DATE NOT NULL,
    team VARCHAR(3) NOT NULL,
    line_number INT,  -- 1, 2, 3, 4 for forwards; 1, 2, 3 for D
    player1_id INT NOT NULL,
    player2_id INT NOT NULL,
    player3_id INT,   -- NULL for D pairs
    toi_together FLOAT,  -- Minutes played together
    source VARCHAR(20),  -- 'shift_chart', 'dailyfaceoff', 'inferred'
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Expected Impact
- **Individual props**: +2-5% hit rate improvement for linemates of predicted stars
- **SGP parlays**: Reduced correlation penalty when stacking linemates intentionally

---

## 4. NHL API vs ODDS PROVIDER GAP ANALYSIS

### Markets We Support vs Available

| Market | Odds Provider | NHL API Data | Current Status |
|--------|---------------|--------------|----------------|
| player_points | ✅ | ✅ game logs | ✅ VALIDATED |
| player_assists | ✅ | ✅ game logs | ✅ VALIDATED |
| player_goals | ✅ | ✅ game logs | ⚠️ Excluded (base rate issue) |
| player_shots_on_goal | ✅ | ✅ game logs | ✅ VALIDATED |
| player_total_saves | ✅ | ✅ boxscore | ✅ VALIDATED (fixed) |
| player_blocked_shots | ✅ | ✅ game logs | ❌ NOT TESTED |
| player_power_play_points | ✅ | ✅ pp_goals, pp_points | ❌ NOT IMPLEMENTED |
| player_goal_scorer_first | ✅ | ⚠️ play-by-play | ❌ NOT IMPLEMENTED |
| player_goal_scorer_anytime | ✅ | ⚠️ play-by-play | ❌ NOT IMPLEMENTED |

### Untapped NHL API Data

| API Endpoint | Data Available | Potential Use |
|--------------|----------------|---------------|
| **Shift Charts** | TOI with specific players | Linemate correlation |
| **NHL Edge - Zone Time** | Offensive/defensive zone % | Saves prediction (already using) |
| **NHL Edge - Shot Speed** | Player avg shot speed | Shots quality signal |
| **NHL Edge - Shot Location** | High-danger shot % | Goals prediction |
| **Play-by-Play** | Event sequence | First/last goal scorer |

### Market Expansion Opportunities

1. **player_blocked_shots** - High volume market, NHL API has data
2. **player_power_play_points** - We track PP stats, easy to add
3. **First Goal Scorer** - Premium odds market, requires play-by-play parsing

---

## 5. MARKET-SPECIFIC MODEL OPTIMIZATION

### Current Reality
All markets use the same signal weights, but they have very different characteristics:

| Market | Natural OVER Rate | Line Distribution | Optimal Threshold |
|--------|------------------|-------------------|-------------------|
| goals | 1.4% (at 1.5) | 90% at 1.5+ | 15% (model works) |
| assists | 35.1% | 99.9% at 0.5 | **5%** |
| points | 49.0% | 93.6% at 0.5 | 15% |
| shots_on_goal | 56.9% (at 1.5) | 51% at 1.5, 41% at 2.5 | **10%** |
| saves | 52.6% | Various | **5%** |

### Recommendation: Market-Specific Signal Weights

```python
MARKET_SIGNAL_WEIGHTS = {
    'assists': {
        'matchup': 0.30,      # 15.3% predictive (highest)
        'usage': 0.25,        # 9.5% predictive
        'line_value': 0.15,   # 3.2% predictive
        'trend': 0.05,        # 4.5% predictive
        # Note: assists are rare events, de-weight overconfidence
    },
    'shots_on_goal': {
        'matchup': 0.25,      # 6.1% predictive
        'line_value': 0.20,   # 3.5% predictive
        'usage': 0.10,        # Only 1.2% predictive for shots
        # Note: shots are more volume-based, less skill-correlated
    },
    # ... etc
}
```

---

## 6. ADDITIONAL OPTIMIZATIONS

### A. Game Context Expansion
Currently using: `game_total`, `spread`

Could add:
- **Pace of play** - Teams that play fast generate more shots/saves
- **Expected game script** - Trailing teams pull goalies, affecting saves
- **Rivalry games** - Higher intensity affects player performance
- **Back-to-back detection** - Already implemented but could be refined

### B. Star Player Detection Enhancement
Current: Used for 4th leg qualification in SGP

Could expand:
- **Star vs weak matchup boost** - When McDavid faces bottom-5 goalie
- **Star home/away splits** - Some stars perform better at home
- **Star recent form weighting** - More weight on star player trends

### C. Goalie-Specific Improvements
Current: Basic save prediction with zone time

Could add:
- **Starter confidence** - Use goalie Edge API `games_above_900` for starter likelihood
- **Workload tracking** - Goalies on back-to-back have lower save %
- **Team shot quality allowed** - Some teams allow more high-danger shots

---

## 7. IMPLEMENTATION PRIORITY MATRIX

| Item | Impact | Effort | Priority |
|------|--------|--------|----------|
| Signal weight rebalancing | HIGH | LOW | **P0 - Do Now** |
| Fix environment signal bug | HIGH | MEDIUM | **P0 - Do Now** |
| Market-specific weights | MEDIUM | MEDIUM | P1 - Next Sprint |
| Linemate stack-with | MEDIUM | HIGH | P1 - Next Sprint |
| Blocked shots market | LOW | LOW | P2 |
| PP points market | LOW | LOW | P2 |
| First goal scorer | LOW | HIGH | P3 |

---

## 8. MONITORING METRICS (Post-Deployment)

Track these daily for the first week:

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Overall leg hit rate | > 52% | < 48% |
| Assists contrarian hit rate | > 60% | < 55% |
| Saves leg hit rate | > 52% | < 48% |
| Parlay win rate | > 5% | < 2% |
| Regression flags shown | 2-5 per day | 0 or > 10 |
| Star legs per day | 10-20% of legs | < 5% or > 30% |

---

## 9. QUICK REFERENCE: FINAL CONFIGURATION

```python
# edge_calculator.py
STAT_CONTRARIAN_THRESHOLDS = {
    'goals': 15.0,         # Model works well
    'saves': 5.0,          # VALIDATED
    'assists': 5.0,        # VALIDATED (+13.7% edge)
    'points': 15.0,        # Less edge, conservative
    'shots_on_goal': 10.0, # VALIDATED (+9.6% edge)
}

# settings.py (RECOMMENDED UPDATE)
SIGNAL_WEIGHTS = {
    'matchup': 0.25,       # ⬆️ Most predictive signal
    'shot_quality': 0.15,  # ⬆️ NHL Edge data
    'goalie_saves': 0.12,  # ⬆️ Validated for saves market
    'game_totals': 0.12,   # ⬆️ Game context
    'usage': 0.12,         # ⬇️ Less predictive than expected
    'line_value': 0.12,    # ➡️ Maintain
    'environment': 0.05,   # ⬇️ Bug - reduce until fixed
    'correlation': 0.04,   # ⬇️ Weak signal
    'trend': 0.03,         # ⬇️ Nearly useless
}
```

---

## Appendix: Backtest Summary

| Market | Props | Hit Rate | Best Edge Bucket | Fade Win Rate |
|--------|-------|----------|------------------|---------------|
| assists | 9,720 | 54.0% | Negative (67.8%) | 63.7% at 5%+ |
| points | 14,943 | 48.3% | Negative (53.4%) | 55.5% at 5%+ |
| shots_on_goal | 22,565 | 47.4% | Negative (50.8%) | 59.6% at 10%+ |
| saves | 947 | 52.6% | Negative (55.0%) | 55.0% at 5%+ |
| goals | N/A | N/A | Model works | N/A |

**Total props analyzed**: 48,175
