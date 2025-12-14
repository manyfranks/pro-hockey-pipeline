# NHL Pipeline API Changes - November 28, 2025

This document outlines recent changes to the NHL prediction pipeline that affect API responses and database schema.

---

## Summary of Changes

1. **Prediction Gating** - New `is_scoreable` field filters meaningful predictions
2. **Structured LLM Output** - New `llm_structured` field provides frontend-friendly JSON
3. **Hit Rate Filtering** - Hit rate calculations now use gated predictions by default

---

## 1. New Database Column: `is_scoreable`

### Table: `nhl_daily_predictions`

**New Column:**
```sql
is_scoreable BOOLEAN DEFAULT FALSE
```

**Computation Logic:**
```
is_scoreable = (line_number <= 3 OR pp_unit >= 1) AND final_score >= 55
```

**What it means:**
- `TRUE` = Core player (Top 3 lines OR Power Play) with meaningful score (≥55)
- `FALSE` = Depth player or low-scoring prediction

**Impact:**
- ~17% of predictions are marked `is_scoreable = TRUE`
- Hit rate for scoreable predictions: **45.8%** (vs 29.7% for all)
- Use this field to filter API responses to only show meaningful picks

### Example Query
```sql
-- Get today's scoreable predictions
SELECT player_name, team, final_score, rank
FROM nhl_daily_predictions
WHERE analysis_date = CURRENT_DATE
  AND is_scoreable = TRUE
ORDER BY rank ASC;
```

---

## 2. New Database Column: `llm_structured`

### Table: `nhl_daily_insights`

**New Column:**
```sql
llm_structured JSONB
```

**Structure:**
```json
{
  "system_health": {
    "status": "hot" | "neutral" | "cold",
    "summary": "2-3 sentence analysis of system performance with hit rate numbers"
  },
  "top_picks": {
    "summary": "3-4 sentence analysis of why the top 3 picks are strong",
    "highlights": ["key point 1", "key point 2", "key point 3"]
  },
  "value_plays": {
    "summary": "2-3 sentence analysis of value picks in positions 4-10",
    "players": ["Player Name 1", "Player Name 2"]
  },
  "caution_flags": {
    "summary": "2-3 sentence warning about risks to watch",
    "concerns": ["concern 1", "concern 2"]
  },
  "parlay_pick": {
    "legs": ["Player Name 1", "Player Name 2"],
    "reasoning": "2-3 sentence explanation of why this parlay makes sense",
    "confidence": "high" | "medium" | "low"
  }
}
```

**Existing Fields (unchanged):**
- `llm_narrative` - Raw LLM text response (kept for backwards compatibility)
- `llm_model` - Model used (e.g., "x-ai/grok-4.1-fast:free")
- `full_report` - Complete insights report as JSONB

### Example Query
```sql
-- Get today's structured LLM insights
SELECT
  analysis_date,
  llm_structured->'system_health'->>'status' as health_status,
  llm_structured->'system_health'->>'summary' as health_summary,
  llm_structured->'parlay_pick'->'legs' as parlay_legs,
  llm_structured->'parlay_pick'->>'confidence' as parlay_confidence
FROM nhl_daily_insights
WHERE analysis_date = CURRENT_DATE;
```

---

## 3. Updated API Response: Hit Rate Summary

### Endpoint: `get_hit_rate_summary()`

**New Parameter:**
```python
scoreable_only: bool = True  # Default changed from False to True
```

**Response Changes:**
```json
{
  "total_predictions": 1758,
  "settled": 1758,
  "excluded": 0,
  "hits": 805,
  "misses": 953,
  "overall_hit_rate": 45.8,
  "scoreable_only": true,  // NEW FIELD
  "by_confidence": [...],
  "by_rank": [...]
}
```

**Behavior:**
- Default (`scoreable_only=true`): Returns stats for gated predictions only
- `scoreable_only=false`: Returns stats for ALL predictions (for analytics)

---

## 4. API Response Examples

### Daily Insights Response

```json
{
  "date": "2025-11-28",
  "generated_at": "2025-11-28T15:13:11.833929",
  "total_predictions": 736,
  "games_count": 15,

  "llm_narrative": "Raw text response...",

  "llm_structured": {
    "system_health": {
      "status": "neutral",
      "summary": "Recent hit rate stands at 33.3% from 2025-11-22 to 2025-11-27, which is stable but below elite levels."
    },
    "top_picks": {
      "summary": "Connor Bedard tops the board at 72.7 facing Nashville's vulnerable defense on Line 1/PP1 with 1.70 PPG over last 10.",
      "highlights": [
        "Bedard's elite deployment and recent form",
        "Kucherov's 7-game point streak",
        "Hughes facing weak San Jose goaltending"
      ]
    },
    "value_plays": {
      "summary": "Nathan MacKinnon at #4 with league-leading 2.00 PPG offers elite upside at a slight discount.",
      "players": ["Nathan MacKinnon", "Cale Makar"]
    },
    "caution_flags": {
      "summary": "System running at 33.3% suggests measured expectations. Colorado trio could underwhelm vs Minnesota's defensive structure.",
      "concerns": [
        "Below-average recent hit rate",
        "Inter-conference games trend lower-scoring"
      ]
    },
    "parlay_pick": {
      "legs": ["Nikita Kucherov", "Nathan MacKinnon"],
      "reasoning": "Combined 3.60 PPG over last 10 with top-line roles. Both face favorable goaltending matchups.",
      "confidence": "medium"
    }
  },

  "llm_model": "x-ai/grok-4.1-fast:free"
}
```

### Predictions Response (with is_scoreable)

```json
{
  "predictions": [
    {
      "rank": 1,
      "player_id": 8482116,
      "player_name": "Connor Bedard",
      "team": "CHI",
      "position": "C",
      "opponent": "NSH",
      "final_score": 72.7,
      "confidence": "high",
      "line_number": 1,
      "pp_unit": 1,
      "recent_ppg": 1.70,
      "point_streak": 1,
      "is_scoreable": true,
      "opposing_goalie_name": "Juuse Saros",
      "opposing_goalie_gaa": 3.08
    },
    {
      "rank": 45,
      "player_name": "Some Fourth Liner",
      "final_score": 52.3,
      "line_number": 4,
      "pp_unit": 0,
      "is_scoreable": false
    }
  ]
}
```

---

## 5. Frontend Implementation Notes

### Filtering Predictions
```javascript
// Only show scoreable predictions to users
const displayPredictions = predictions.filter(p => p.is_scoreable === true);
```

### Rendering LLM Insights
```javascript
const { llm_structured } = dailyInsights;

// Health status badge
const healthBadge = {
  hot: { color: 'green', label: '🔥 Hot' },
  neutral: { color: 'yellow', label: '➖ Neutral' },
  cold: { color: 'red', label: '❄️ Cold' }
}[llm_structured.system_health.status];

// Parlay confidence badge
const confidenceBadge = {
  high: { color: 'green', label: 'High Confidence' },
  medium: { color: 'yellow', label: 'Medium Confidence' },
  low: { color: 'red', label: 'Low Confidence' }
}[llm_structured.parlay_pick.confidence];
```

### Displaying Hit Rate
```javascript
// The API now returns gated hit rate by default
// No frontend filtering needed - just display the number
const hitRateDisplay = `${hitRateSummary.overall_hit_rate}%`;

// Show indicator that this is filtered
const filterNote = hitRateSummary.scoreable_only
  ? "Core players only"
  : "All predictions";
```

---

## 6. Migration Notes

### Database Migration Required
Run the migration script after deploying code changes:
```bash
python scripts/migrate_add_is_scoreable.py
```

This will:
1. Add `is_scoreable` column to `nhl_daily_predictions`
2. Backfill all existing records
3. Add `llm_structured` column to `nhl_daily_insights`

### Backwards Compatibility
- `llm_narrative` field is preserved (raw text)
- `full_report` field is preserved
- Setting `scoreable_only=False` returns legacy behavior

---

## 7. Key Metrics

| Metric | Before Gating | After Gating |
|--------|---------------|--------------|
| Daily predictions | ~700 | ~120 scoreable |
| All-time hit rate | 29.7% | **45.8%** |
| Recent (5-day) hit rate | 22.3% | **33.3%** |

---

## Questions?

Contact the pipeline team for implementation support.
