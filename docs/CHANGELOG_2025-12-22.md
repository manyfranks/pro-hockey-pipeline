# NHL Pipeline Optimization Changelog
**Date**: December 22, 2025
**Version**: 2.1.0

## Summary

This release addresses critical performance issues identified in 2-month backtest analysis:
- **Score inversion fix**: High model scores (85+) had 15.2% hit rate vs 77.2% for 70-74 range
- **SGP parlay optimization**: 0% win rate (0/58) due to leg length and confidence thresholds
- **Saves signal rewrite**: Complete overhaul based on NHL Edge API zone time data

---

## Database Schema Changes

### REQUIRED MIGRATION: `nhl_sgp_legs` table

Add new column for star player leg tracking:

```sql
-- Run this migration before deploying
ALTER TABLE nhl_sgp_legs
ADD COLUMN IF NOT EXISTS is_star_leg BOOLEAN DEFAULT FALSE;

-- Add comment for documentation
COMMENT ON COLUMN nhl_sgp_legs.is_star_leg IS
  'Indicates if this leg qualified as a "star player" edge (allows 4th leg)';
```

### No Schema Changes Required (JSONB)

The following new fields are stored within existing JSONB columns:

**In `nhl_daily_predictions.component_details`:**
- `regression_flags` (array of strings): `['HOT_STREAK_PENALTY', 'PPG_CAPPED', 'OVERCONFIDENCE_PENALTY']`
- `regression_explanation` (string): Human-readable explanation for analytics
- `raw_final_score` (float): Score before overconfidence penalty applied
- `is_overconfident` (boolean): True if raw score exceeded threshold
- `overconfidence_penalty` (float): Points deducted from raw score

**In `nhl_sgp_legs.signals`:**
- Saves signal now includes: `zone_time_factor`, `game_total_factor`, `polarity_inverted`
- All signals may include `contrarian_applied` flag

---

## API Response Changes

### Player Rankings Endpoint

New fields in player prediction objects:

```json
{
  "player_name": "Connor McDavid",
  "final_score": 69.2,
  "raw_final_score": 84.2,
  "is_overconfident": true,
  "regression_flags": ["HOT_STREAK_PENALTY", "OVERCONFIDENCE_PENALTY"],
  "regression_explanation": "REGRESSION ADJUSTMENT: Player PPG (2.40) exceeds sustainable threshold. Flags: HOT_STREAK_PENALTY, OVERCONFIDENCE_PENALTY. Raw score 84.2 adjusted to 69.2. Reason: Historical 85+ scores hit only 15.2% vs 77.2% for 70-74 range."
}
```

**Frontend Considerations:**
- Display `final_score` as the primary ranking metric
- Show `regression_flags` as warning badges/chips if present
- Use `regression_explanation` for tooltip/hover details
- Consider visual indicator when `is_overconfident` is true

### SGP Parlay Endpoint

New fields in leg objects:

```json
{
  "legs": [
    {
      "player_name": "Kyle Connor",
      "stat_type": "assists",
      "is_star_leg": true,
      "primary_reason": "[CONTRARIAN] Faded OVER → UNDER: ..."
    }
  ]
}
```

**Frontend Considerations:**
- `is_star_leg: true` indicates this leg enabled a 4th leg on the parlay
- `[CONTRARIAN]` prefix in `primary_reason` indicates the direction was flipped
- Parlays now range from 2-4 legs (previously fixed at 4)

---

## Behavioral Changes

### 1. Tiered Parlay System

| Config | Old Value | New Value | Reason |
|--------|-----------|-----------|--------|
| MIN_LEGS_PER_PARLAY | 4 | 2 | Reduce parlay complexity |
| BASE_MAX_LEGS | 4 | 3 | Standard parlay ceiling |
| MAX_LEGS_PER_PARLAY | 4 | 4 | Only with star player edge |
| MIN_CONFIDENCE | 0.70 | 0.55 | Signals only reach 0.55-0.65 |

**Star Player Criteria** (for 4th leg):
- `min_confidence`: 0.60
- `direction`: 'over' only
- `max_line`: 0.5 (recording points)
- `stat_types`: ['points', 'assists']
- `edge`: 3.0% to 10.0% (moderate edge, not extreme)

### 2. Regression Penalty System

Players with extreme recent performance now receive score penalties:

| Condition | Penalty | Threshold |
|-----------|---------|-----------|
| PPG > 2.0 (last 10 games) | -15% on form score | REGRESSION_PENALTY_FACTOR |
| Raw score > 80 | -15 points | OVERCONFIDENCE_PENALTY |
| PPG > 1.5 | Capped at 1.5 | PPG_CAP |

**Result**: Hot streak players rank LOWER than steady performers, matching empirical hit rates.

### 3. Saves Signal Overhaul

Complete rewrite with inverted polarity:

| Component | Weight | Description |
|-----------|--------|-------------|
| Zone Time | 25% | NHL Edge API offensive zone % |
| Game Total | 15% | O/U correlation (-0.3 for high totals) |
| Opponent SOG | 30% | Team shots allowed trend |
| Goalie Form | 15% | Recent save percentage |
| Expected vs Line | 15% | Gap from projected saves |

**Critical**: Signal polarity is INVERTED. Positive raw signal → negative final signal.
Contrarian threshold for saves is 5% (more aggressive than 15% for other markets).

### 4. Stat-Specific Contrarian Thresholds

| Stat Type | Threshold | Backtest Status |
|-----------|-----------|-----------------|
| goals | 15.0% | Model OVER picks hit 25% vs 1.4% base rate - WORKING! |
| saves | 5.0% | **VALIDATED** - 55.0% neg edge vs 41.8% at 5-10% (947 props) |
| assists | 5.0% | **VALIDATED** - Fade 5%+ OVER → 63.7% win rate (9,720 props) |
| points | 15.0% | **VALIDATED** - Fade 5%+ OVER → 55.5% (less edge, keep 15%) |
| shots_on_goal | 10.0% | **VALIDATED** - Fade 10%+ OVER → 59.6% win rate (22,565 props) |

### 5. Saves Backtest Results (VALIDATED Dec 22, 2025)

**Settlement fix applied** - goalie saves now properly fetched from box scores.

| Metric | Value | Insight |
|--------|-------|---------|
| Props tested | 947 | Nov 1 - Dec 15, 2025 |
| Overall hit rate | **52.6%** | Above 50% baseline |
| Negative edge | **55.0%** | Fading model = best performance |
| 0-5% edge | **52.2%** | Near baseline |
| 5-10% edge | **41.8%** | High-edge underperforms |

**Conclusion**: Saves market shows same inverted edge pattern as other markets.
Set contrarian threshold to 5.0% for saves (vs 15% default) due to clearer signal.

### 6. Assists Backtest Results (VALIDATED Dec 22, 2025)

| Metric | Value | Insight |
|--------|-------|---------|
| Props tested | 9,720 | Nov 1 - Dec 15, 2025 |
| Line distribution | 99.9% at 0.5 | Single-assist threshold |
| Natural OVER rate | **35.1%** | ~1/3 of players get 1+ assists |
| Model OVER hit | 38.3% | +3.2% above base (model works) |
| 10%+ edge OVER | **36.1%** | Barely above base rate |
| Fade 5%+ OVER | **63.7%** | +13.7% edge! |

**Key Finding**: Model signals point OVER for "good" players, but assists are rare events.
High-confidence OVER picks don't beat base rates. **Fading provides 13.7% edge.**

### 7. Points Backtest Results (VALIDATED Dec 22, 2025)

| Metric | Value | Insight |
|--------|-------|---------|
| Props tested | 14,943 | Nov 1 - Dec 15, 2025 |
| Natural OVER (0.5 line) | **49.0%** | Nearly balanced market |
| Fade 5%+ OVER | **55.5%** | +5.5% edge |
| Fade 10%+ OVER | **55.5%** | Same edge, fewer props |

**Conclusion**: Points shows less inversion than assists. Keep threshold at 15%.

### 8. Shots on Goal Backtest Results (VALIDATED Dec 22, 2025)

| Metric | Value | Insight |
|--------|-------|---------|
| Props tested | 22,565 | Nov 1 - Dec 15, 2025 |
| Line distribution | 51% at 1.5, 41% at 2.5 | Mixed lines |
| Natural OVER (1.5) | **56.9%** | Majority hit 2+ shots |
| Natural OVER (2.5) | **45.7%** | Near balanced |
| Fade 10%+ OVER | **59.6%** | +9.6% edge |

**Conclusion**: Set threshold to 10.0% for shots_on_goal.

### 9. Backtest Reality Check (Goals)

**Initial analysis was WRONG due to:**

1. **Goals lines are 1.5/2.5** (90% of props) - UNDER wins 98%+ naturally
   - "80.9% negative edge hit rate" = just betting UNDER on rare events
   - Model OVER picks actually hit 25% vs 1.4% base rate (model is 18x better!)

**Lesson: Always check base rates and data quality before drawing conclusions!**

---

## Files Changed

### Core Algorithm
- `analytics/recent_form_calculator.py` - PPG cap, regression penalty
- `analytics/final_score_calculator.py` - Overconfidence penalty, transparency fields

### Pipeline
- `pipeline/nhl_prediction_pipeline.py` - Display regression flags in output

### SGP Engine
- `nhl_sgp_engine/scripts/daily_sgp_generator.py` - Tiered parlay system
- `nhl_sgp_engine/edge_detection/edge_calculator.py` - Stat-specific thresholds (saves=5.0%)
- `nhl_sgp_engine/signals/goalie_saves_signal.py` - Complete rewrite
- `nhl_sgp_engine/scripts/signal_backtest.py` - **Fixed saves settlement** (added goalie context)

### API Integration
- `providers/nhl_official_api.py` - `get_team_zone_time()` for NHL Edge API

---

## Monitoring Checklist (First Week)

1. **Parlay Generation**: Should see 2-4 leg parlays (mostly 2-3)
2. **Star Legs**: ~10-20% of parlays should have `is_star_leg: true`
3. **Regression Flags**: Top 25 players should show 2-5 with flags
4. **Score Distribution**: 85+ scores should be rare (< 5% of predictions)
5. **Saves Performance**: With 5.0% contrarian threshold, expect ~55% hit rate on saves legs

---

## Rollback Plan

If issues occur:

```python
# In daily_sgp_generator.py
MIN_LEGS_PER_PARLAY = 4  # Revert to old value
MIN_CONFIDENCE = 0.70    # Revert to old value

# In final_score_calculator.py
OVERCONFIDENCE_PENALTY = 0.0  # Disable penalty

# In recent_form_calculator.py
PPG_CAP = 3.0  # Raise cap
REGRESSION_PENALTY_FACTOR = 0.0  # Disable penalty
```

---

## Questions?

Contact the data engineering team for:
- Schema migration assistance
- API response format clarification
- Signal calculation details
