# NHL Pipeline: Player Analytics & LLM Insights Implementation Summary

**Document Version:** 1.0
**Last Updated:** 2025-11-28
**Prepared For:** Cross-League Team Reference

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Player Analytics Engine](#player-analytics-engine)
4. [Post-Scoring Settlement Pipeline](#post-scoring-settlement-pipeline)
5. [Insights Generation](#insights-generation)
6. [LLM Integration](#llm-integration)
7. [Daily Pipeline Orchestration](#daily-pipeline-orchestration)
8. [Database Schema](#database-schema)
9. [Configuration & Environment](#configuration--environment)
10. [Key Learnings & Calibration Notes](#key-learnings--calibration-notes)

---

## Executive Summary

The NHL Pro-Hockey Pipeline is a production-ready prediction system that:
- **Generates daily predictions** for player point scoring (1+ point threshold)
- **Settles previous predictions** against actual box score results
- **Produces rule-based insights** (parlays, hot streaks, goalie vulnerabilities)
- **Generates LLM-powered narrative analysis** via OpenRouter/Claude/OpenAI

**Key Statistics:**
- Composite score range: 0-100
- Primary predictor: Line opportunity (45% weight, r=+0.14 correlation)
- LLM output: Structured JSON for programmatic consumption

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DAILY PIPELINE ORCHESTRATOR                           │
│                     (scripts/daily_orchestrator.py)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │
│  │  1. SETTLEMENT  │───▶│  2. PREDICTIONS │───▶│   3. INSIGHTS   │          │
│  │   (Yesterday)   │    │     (Today)     │    │     (Today)     │          │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘          │
│           │                      │                      │                    │
│           ▼                      ▼                      ▼                    │
│   ┌───────────────┐      ┌───────────────┐      ┌───────────────┐           │
│   │ Box Scores    │      │ Analytics     │      │ Rule-Based    │           │
│   │ NHL API       │      │ Engine        │      │ (Phase 0)     │           │
│   │ Hit/Miss/DNP  │      │ Final Score   │      │               │           │
│   └───────────────┘      └───────────────┘      │ LLM-Powered   │           │
│                                                 │ (Phase 1)     │           │
│                                                 └───────────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key File Locations

| Component | File Path |
|-----------|-----------|
| **Orchestrator** | `scripts/daily_orchestrator.py` |
| **Final Score Calculator** | `analytics/final_score_calculator.py` |
| **Settlement Pipeline** | `pipeline/settlement.py` |
| **Rule-Based Insights** | `analytics/insights_generator.py` |
| **LLM Insights** | `analytics/llm_insights.py` |
| **Database Manager** | `database/db_manager.py` |

---

## Player Analytics Engine

### Scoring Algorithm (Updated 2024-11-25)

The final composite score is calculated on a **0-100 scale** using weighted components:

```python
final_score = (
    line_opportunity_score * 45 +    # PRIMARY predictor (r=+0.14)
    situational_score * 25 +         # Fatigue, home/away bonuses
    recent_form_score * 20 +         # PPG capped at 2.0 to prevent regression
    matchup_score * 10               # Conditional goalie weakness by player tier
)
```

### Component Breakdown

#### 1. Line Opportunity Score (45% Weight)
**File:** `analytics/line_opportunity_calculator.py`

Combines three sub-components:
- **Line Number (50%):** 1st line = 1.0, 2nd = 0.70, 3rd = 0.40, 4th = 0.15
- **Power Play Unit (35%):** PP1 = +0.30, PP2 = +0.15, None = 0.0
- **Average TOI (15%):** Normalized against elite TOI benchmark (22 min)

```python
LINE_SCORES = {1: 1.00, 2: 0.70, 3: 0.40, 4: 0.15}
PP_BONUSES = {0: 0.00, 1: 0.30, 2: 0.15}
```

**Role Tier Classification:**
- `elite`: Line 1 + PP1
- `top_6_pp`: Line 1-2 + PP1/PP2
- `top_6`: Line 1-2, no PP
- `middle_6`: Line 3
- `depth`: Line 4

#### 2. Situational Score (25% Weight)
**File:** `analytics/situational_analyzer.py`

Handles fatigue and context-based adjustments:

| Factor | Adjustment |
|--------|------------|
| Home ice | +3% |
| Back-to-back (B2B) | -8% |
| B2B2B (3 games in 3 nights) | -15% |
| Opposing goalie on B2B | +10% |
| Opposing goalie well-rested (2+ days) | -5% |
| Road trip 4+ games | -5% |
| Road trip 6+ games | -10% |

**Implementation Highlights:**
- `ScheduleAnalyzer` class caches team schedules for efficient B2B detection
- Detects consecutive away games for road trip fatigue
- Opposing goalie fatigue provides scoring boost

#### 3. Recent Form Score (20% Weight)
**File:** `analytics/recent_form_calculator.py`

**Critical Calibration Finding:** Players with PPG > 3.0 had the *worst* hit rate (11.9%) due to regression to mean.

**Solution Implemented:**
```python
PPG_CAP = 2.0  # Cap PPG to prevent over-crediting hot streaks

# Streak bonuses (REDUCED from original)
STREAK_BONUS_3_GAMES = 0.02  # Was 0.05
STREAK_BONUS_5_GAMES = 0.05  # Was 0.10
```

Normalization: `normalized_ppg = min(capped_ppg / 1.5, 1.0)`

#### 4. Matchup Score (10% Weight)
**File:** `analytics/final_score_calculator.py` (lines 88-162)

**Key Insight:** Raw goalie weakness as a standalone weight *hurt* predictions (r=-0.04).

**Paradox Identified:** Players facing GOOD goalies had BETTER hit rates than those facing BAD goalies.

**Root Cause:** Bad goalies play for bad teams with bad offenses (confounding variable).

**Solution - Conditional Goalie Weakness:**
```python
if is_elite (L1+PP1):
    matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.6  # 60% impact
elif is_top6 and is_pp_player:
    matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.4  # 40% impact
elif is_top6:
    matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.2  # 20% impact
else:  # Depth players
    matchup_score = 0.5  # Near neutral (goalie doesn't help them score)
```

### Confidence Tier Calculation

```python
def _calculate_confidence_tier(player_data):
    # very_high: Top line + PP1 + hot streak + 2+ game point streak
    # high: Top 6 + PP + PPG >= 0.6 + 5+ recent games
    # medium: Top 9 + 3+ recent games
    # low: Everything else
```

---

## Post-Scoring Settlement Pipeline

**File:** `pipeline/settlement.py`

### Settlement Outcome Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `1` | HIT | Player recorded 1+ points |
| `0` | MISS | Player recorded 0 points |
| `2` | PPD | Game was postponed |
| `3` | DNP | Player did not play (scratched, injured, etc.) |

### Settlement Workflow

```
1. Fetch unsettled predictions from database (by date)
2. Retrieve box scores from NHL Official API (api-web.nhle.com)
3. Match player stats to predictions:
   - Check game status (OFF/FINAL = complete, PPD = postponed)
   - Find player in box score by player_id
   - Check ice time (TOI = '00:00' means DNP)
   - Extract goals, assists, calculate points
4. Update database with settlement results
5. Calculate hit rate for performance tracking
```

### Key Methods

```python
class SettlementPipeline:
    def settle_date(self, settlement_date: date, dry_run: bool = False)
    def settle_date_range(self, start_date: date, end_date: date)
    def get_performance_report(self, start_date: date, end_date: date)
```

### Box Score Matching Logic

```python
# NHL Official API format
for player in box_scores[game_id]['players']:
    if player.get('player_id') == predicted_player_id:
        toi = player.get('toi')  # "MM:SS" format
        if not toi or toi == '00:00':
            outcome = OUTCOME_DNP
        else:
            points = player.get('goals', 0) + player.get('assists', 0)
            outcome = OUTCOME_HIT if points >= 1 else OUTCOME_MISS
```

---

## Insights Generation

### Phase 0: Rule-Based Insights
**File:** `analytics/insights_generator.py`

Generates structured insights without LLM:

#### Insight Types

1. **Hot Streaks** (`PlayerInsight`)
   - Threshold: 3+ game point streak OR 1.2+ recent PPG
   - Sub-types: `extended_hot_streak` (5+), `hot_streak` (3+), `high_ppg`

2. **Elite Opportunities** (`PlayerInsight`)
   - Criteria: Line 1 + PP1 + weak goalie (below_average or poor tier)

3. **PP Specialists** (`PlayerInsight`)
   - Criteria: PP1 + 3+ power play goals on season

4. **Goalie Vulnerabilities** (`GoalieInsight`)
   - Thresholds: GAA >= 3.2 OR SV% <= 0.890
   - Sub-types: `high_gaa`, `low_sv_pct`, `cold_streak`

5. **Matchup Highlights** (`MatchupInsight`)
   - Stack opportunities: 3+ top-25 players in same game
   - Goalie mismatches

#### Parlay Recommendations

```python
parlays = {
    'conservative': 2-leg from different games (est. 35% hit prob),
    'balanced': 3-leg position-diverse (est. 20% hit prob),
    'aggressive': 4-leg PP1 specialists (est. 12% hit prob),
    'moonshot': 5-leg hot streaks (est. 7% hit prob)
}
```

**Diversity Selection:**
- By game: Avoids correlated outcomes from same game
- By position: Ensures C/W/D mix
- By team: Spreads risk across teams

### InsightsReport Data Structure

```python
@dataclass
class InsightsReport:
    analysis_date: str
    generated_at: str
    total_predictions: int
    hot_streaks: List[PlayerInsight]
    elite_opportunities: List[PlayerInsight]
    pp_specialists: List[PlayerInsight]
    goalie_vulnerabilities: List[GoalieInsight]
    matchup_highlights: List[MatchupInsight]
    parlays: Dict[str, ParlayRecommendation]
    top_5_picks: List[Dict]
    picks_6_to_10: List[Dict]
    recent_performance: Optional[Dict]  # From settlement data
```

---

## LLM Integration

**File:** `analytics/llm_insights.py`

### Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    LLMInsightsGenerator                        │
├───────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────────────────┐ │
│  │ SettlementDataCollector │  │ LLMPromptBuilder          │ │
│  │ - get_recent_settlements │  │ - SYSTEM_PROMPT          │ │
│  │ - _get_daily_breakdown  │  │ - build_analysis_prompt  │ │
│  │ - _identify_patterns    │  │                           │ │
│  └─────────────────────────┘  └─────────────────────────────┘ │
│                               │                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    LLM Providers                         │  │
│  │   OpenRouter (default) │ Anthropic │ OpenAI             │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### LLM Configuration

```python
@dataclass
class LLMConfig:
    provider: str = "openrouter"  # "anthropic", "openai", or "openrouter"
    model: str = None  # Defaults: openrouter=gemini-2.0-flash, anthropic=claude-3.5-sonnet
    max_tokens: int = 2000
    temperature: float = 0.7
```

### System Prompt

```python
SYSTEM_PROMPT = """You are an expert NHL analytics assistant...

Your tone should be:
- Confident but not overconfident
- Data-driven with specific numbers
- Honest about uncertainty
- Focused on actionable advice

IMPORTANT: You MUST respond with valid JSON only. No markdown, no extra text.
Your response must be parseable by JSON.parse()."""
```

### Prompt Data Structure

The LLM receives:
1. **Top 10 Predictions** - Player, team, opponent, score, streak, PPG, line/PP
2. **Settlement Summary** - Recent hit rates, trends
3. **Hot Streaks** - Players on point streaks with stats
4. **Goalie Vulnerabilities** - Weak goalies with GAA/SV%

### Expected LLM JSON Response

```json
{
  "system_health": {
    "status": "hot" | "neutral" | "cold",
    "summary": "2-3 sentence analysis with specific hit rate numbers"
  },
  "top_picks": {
    "summary": "3-4 sentence analysis of why top 3 picks are strong",
    "highlights": ["key point 1", "key point 2", "key point 3"]
  },
  "value_plays": {
    "summary": "2-3 sentence analysis of positions 4-10",
    "players": ["player name 1", "player name 2"]
  },
  "caution_flags": {
    "summary": "2-3 sentence warning about risks",
    "concerns": ["concern 1", "concern 2"]
  },
  "parlay_pick": {
    "legs": ["Player Name 1", "Player Name 2"],
    "reasoning": "2-3 sentence explanation",
    "confidence": "high" | "medium" | "low"
  }
}
```

### Response Parsing

```python
def _parse_llm_response(self, response: str) -> Optional[Dict]:
    # Extract JSON from response (handles LLM adding extra text)
    json_match = re.search(r'\{[\s\S]*\}', response)
    if json_match:
        return json.loads(json_match.group())
    return None
```

### Fallback Handling

When LLM is unavailable:
```python
def _generate_fallback(self, prompt: str) -> str:
    return """**LLM Analysis Unavailable**

    LLM insights could not be generated (API key not configured or service unavailable).

    Please review the rule-based insights above for:
    - Hot streak players
    - Elite opportunities (Top line + PP1 vs weak goalie)
    - Parlay recommendations

    To enable LLM insights, set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."""
```

### Database Caching

LLM responses are cached to avoid regeneration costs:

```python
self.db.upsert_daily_insights(
    analysis_date=analysis_date_obj,
    llm_narrative=report.get('llm_narrative'),
    llm_structured=report.get('llm_structured'),  # JSON blob
    llm_model=self.llm_config.model,
    full_report=self._make_json_safe(report),
    total_predictions=report.get('total_predictions', 0),
    games_count=report.get('games_count', 0)
)
```

---

## Daily Pipeline Orchestration

**File:** `scripts/daily_orchestrator.py`

### Command-Line Interface

```bash
# Run full pipeline for today
python -m scripts.daily_orchestrator

# Run for specific date
python -m scripts.daily_orchestrator --date 2025-11-26

# Skip LLM insights
python -m scripts.daily_orchestrator --no-llm

# Dry run (don't write to database)
python -m scripts.daily_orchestrator --dry-run

# Force refresh all data from APIs
python -m scripts.daily_orchestrator --force-refresh
```

### Pipeline Stages

```
┌────────────────────────────────────────────────────────────────────┐
│ STAGE 1: SETTLEMENT (Yesterday)                                    │
│   - Fetch unsettled predictions                                    │
│   - Retrieve box scores from NHL API                              │
│   - Match predictions to actual results                           │
│   - Update database with hit/miss/dnp/ppd outcomes               │
├────────────────────────────────────────────────────────────────────┤
│ STAGE 2: PREDICTIONS (Today)                                       │
│   - Get today's scheduled games                                   │
│   - Enrich player data (rosters, lines, goalies, stats)          │
│   - Calculate component scores                                    │
│   - Generate final 0-100 composite scores                        │
│   - Rank and save to database                                    │
├────────────────────────────────────────────────────────────────────┤
│ STAGE 3: INSIGHTS (Today)                                          │
│   - Phase 0: Rule-based insights (parlays, hot streaks)          │
│   - Phase 1: LLM narrative analysis (if enabled)                 │
│   - Save both to nhl_daily_insights table                        │
└────────────────────────────────────────────────────────────────────┘
```

### Output Summary

```
================================================================================
PIPELINE SUMMARY
================================================================================
Settlement: OK - 45 settled, 58.2% hit rate
Predictions: OK - 127 predictions generated
Insights: OK - 4 parlays, LLM generated

================================================================================
PIPELINE STATUS: SUCCESS
================================================================================
```

---

## Database Schema

### Key Tables

#### `nhl_daily_predictions`
```sql
- player_id (INT)
- game_id (INT)
- analysis_date (DATE)
- player_name (VARCHAR)
- team (VARCHAR)
- opponent (VARCHAR)
- final_score (DECIMAL)
- rank (INT)
- confidence (VARCHAR)
- line_number (INT)
- pp_unit (INT)
- is_scoreable (BOOLEAN)  -- Top 3 lines OR PP with score >= 55
- point_outcome (INT)  -- NULL until settled
- actual_points (INT)
- actual_goals (INT)
- actual_assists (INT)
- component_scores (JSONB)
```

#### `nhl_settlements`
```sql
- player_id (INT)
- game_id (INT)
- analysis_date (DATE)
- actual_points (INT)
- actual_goals (INT)
- actual_assists (INT)
- point_outcome (INT)  -- 0=MISS, 1=HIT, 2=PPD, 3=DNP
- player_name (VARCHAR)
- rank (INT)
```

#### `nhl_daily_insights`
```sql
- analysis_date (DATE)
- llm_narrative (TEXT)
- llm_structured (JSONB)  -- Parsed JSON from LLM
- llm_model (VARCHAR)
- full_report (JSONB)
- total_predictions (INT)
- games_count (INT)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)
```

### is_scoreable Filter

```python
# Migration: scripts/migrate_add_is_scoreable.py
# Definition: "Core" predictions for tracking purposes
is_scoreable = (
    (line_number <= 3 OR pp_unit > 0) AND
    final_score >= 55
)
```

---

## Configuration & Environment

### Required Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:password@host:5432/sports_analytics

# LLM Configuration (OpenRouter is default)
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL_NAME=google/gemini-2.0-flash-001

# Alternative LLM Providers
ANTHROPIC_API_KEY=sk-ant-...  # For Claude
OPENAI_API_KEY=sk-...         # For OpenAI

# Optional
LOG_LEVEL=INFO
DAILYFACEOFF_CACHE_TTL_HOURS=6
```

### Data Providers

| Provider | Source | Data |
|----------|--------|------|
| NHL Official API | api-web.nhle.com | Games, rosters, box scores, player stats |
| DailyFaceoff | dailyfaceoff.com (scraper) | Line combinations, PP units |

---

## Key Learnings & Calibration Notes

### Empirical Findings (2024-11-25 Analysis of 3,163 Predictions)

1. **Line Opportunity is the BEST Predictor**
   - Correlation: r=+0.14 with actual points
   - PP1 status more predictive than line number alone

2. **Recent Form Shows Negative Correlation in Top Ranks**
   - Players with PPG 3.0+ had WORST hit rate (11.9%)
   - Sweet spot: PPG 2.0-3.0 (21.6% hit rate)
   - **Solution:** Cap PPG at 2.0

3. **Raw Goalie Weakness HURTS Predictions**
   - Correlation: r=-0.04 (negative!)
   - Paradox: Good teams face good goalies but their stars still score
   - **Solution:** Apply goalie weakness conditionally by player tier

4. **Situational Factors Have Good Effect Size**
   - B2B fatigue effect: +0.21 (meaningful)
   - Home ice advantage: ~3%

### Recommended Adaptations for Other Leagues

1. **Identify the Primary Predictor**
   - Run correlation analysis on settled predictions
   - Weight your algorithm accordingly

2. **Cap Hot Streak Metrics**
   - High recent performance often regresses
   - Find your league's "sweet spot"

3. **Apply Conditional Logic**
   - Context matters (e.g., star players vs depth)
   - Don't use raw metrics; consider player tier

4. **Use Structured LLM Output**
   - Force JSON responses for programmatic parsing
   - Include fallback for LLM failures
   - Cache expensive LLM calls

5. **Maintain Settlement Pipeline**
   - Critical for algorithm calibration
   - Track hit rates by rank, tier, and time period

---

## Appendix: Quick Reference

### File-to-Feature Map

```
analytics/
├── final_score_calculator.py    ← 0-100 composite score
├── recent_form_calculator.py    ← PPG with 2.0 cap
├── line_opportunity_calculator.py ← Line + PP + TOI
├── goalie_weakness_calculator.py  ← Opposing goalie stats
├── matchup_analyzer.py          ← Skater-vs-Goalie history
├── situational_analyzer.py      ← B2B, fatigue, home/away
├── insights_generator.py        ← Phase 0 rule-based
└── llm_insights.py              ← Phase 1 LLM-powered

pipeline/
├── nhl_prediction_pipeline.py   ← Daily predictions
├── enrichment.py                ← Data enrichment
└── settlement.py                ← Post-game settlement

scripts/
├── daily_orchestrator.py        ← Main entry point
├── backfill_predictions.py      ← Historical generation
└── migrate_add_is_scoreable.py  ← DB migration
```

### API Response Processing

```python
# LLM structured response access
report['llm_structured']['top_picks']['summary']
report['llm_structured']['parlay_pick']['legs']
report['llm_structured']['system_health']['status']
```

---

*Document prepared by automated audit of NHL Pro-Hockey Pipeline codebase.*
