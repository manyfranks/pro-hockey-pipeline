# NBA SGP Engine - Backtest Analysis & Production Readiness

**Date**: December 2025
**Analysis Type**: Deep dive on data trustworthiness and production gaps

---

## 1. Can We Trust This Data?

### 1.1 Statistical Significance

| Metric | Value | Concern Level |
|--------|-------|---------------|
| Sample Size | 35 parlays, 105 legs | ⚠️ **HIGH** |
| Non-void Parlays | 27 | ⚠️ **HIGH** |
| Win Rate | 59.3% | ✅ Promising |
| 95% Confidence Interval | **40.7% to 77.8%** | ⚠️ **HIGH** |
| Required Sample (5% margin) | ~96 parlays | Need 3.5x more data |

**Verdict**: The sample size is too small to be statistically confident. The true win rate could be anywhere from 41% to 78%. We need at least 96 parlays for meaningful validation.

### 1.2 Data Quality Issues

| Issue | Severity | Count | Impact |
|-------|----------|-------|--------|
| Void Legs | High | 27/105 (25.7%) | Reduces usable sample |
| Missing Players | Medium | ~10 names | Luka Doncic, Herb Jones, etc. |
| Threes Props | High | 3/3 void | Can't settle this stat type |
| Date Imbalance | Medium | Nov dates overweight | Cup vs regular season |

### 1.3 Edge Calculation Clarification

The "edge_pct" in our system is **not** a traditional betting edge. It's a **signal strength score** (-100% to +100%):

| Signal Strength | Hit Rate | Interpretation |
|-----------------|----------|----------------|
| 40-60% | 78% | Strong signal, good predictive value |
| 60%+ | 70% | Very strong signal, slight regression |
| Overall OVER | 71% | Solid performance |
| Overall UNDER | 100% (n=8) | Too small to trust |

### 1.4 Potential Biases

1. **Look-Ahead Bias**: Using December player stats to evaluate November games
   - Mitigation: Player IDs are consistent, but season averages change

2. **Selection Bias**: Only NBA Cup games tested
   - Cup games have different dynamics (elimination stakes, neutral sites)
   - Need regular season validation

3. **Survivorship Bias**: High void rate (25.7%) means we only evaluate "clean" games
   - Players who DNP are excluded from analysis

### 1.5 Recommendation

**DO NOT deploy to production with live money** until:
- [ ] Backtest on 100+ additional parlays
- [ ] Include regular season games
- [ ] Fix player name matching (Doncic, Jones, etc.)
- [ ] Investigate threes prop void issue
- [ ] Paper trade for 2-4 weeks

---

## 2. Production Deployment Gaps

### 2.1 Missing Infrastructure

| Component | Status | Priority |
|-----------|--------|----------|
| Dockerfile | ❌ Missing | HIGH |
| railway.toml | ❌ Missing | HIGH |
| Cron schedule | ❌ Missing | HIGH |
| Health checks | ❌ Missing | MEDIUM |
| Logging/monitoring | ❌ Missing | MEDIUM |
| API documentation | ❌ Missing | MEDIUM |
| Frontend spec | ❌ Missing | LOW (for now) |

### 2.2 Recommended Cron Schedule

```
# NBA game times (Eastern):
# - Afternoon: 12:00-3:00 PM (rare)
# - Evening: 7:00-8:00 PM (most common)
# - Late: 10:00-10:30 PM (West Coast)

# Recommended schedule:
0 14 * * *    # 2 PM ET - Fetch today's props
0 18 * * *    # 6 PM ET - Re-fetch with injury updates
0 10 * * *    # 10 AM ET - Settle yesterday's parlays
```

### 2.3 Required Files

**Dockerfile** needed for Railway deployment
**railway.toml** for service configuration
**requirements.txt** should be reviewed for production deps

---

## 3. API & Frontend Documentation Needs

### 3.1 Core API Endpoints Needed

```
GET  /api/v1/parlays/today         # Today's recommended parlays
GET  /api/v1/parlays/:date         # Parlays for specific date
GET  /api/v1/parlays/:id           # Single parlay details
GET  /api/v1/settlements/:date     # Settlement results
GET  /api/v1/performance           # Overall performance metrics
GET  /api/v1/players/:name/history # Player prop history
POST /api/v1/props/analyze         # Analyze custom prop
```

### 3.2 Frontend Data Needs

```typescript
interface Parlay {
  id: string;
  gameDate: string;
  homeTeam: string;
  awayTeam: string;
  legs: Leg[];
  combinedOdds: number;
  thesis: string;
  status: 'pending' | 'win' | 'loss' | 'void';
}

interface Leg {
  playerName: string;
  team: string;
  statType: string;
  line: number;
  direction: 'over' | 'under';
  odds: number;
  edgePct: number;
  confidence: number;
  result?: 'WIN' | 'LOSS' | 'PUSH' | 'VOID';
  actualValue?: number;
}

interface Performance {
  totalParlays: number;
  wins: number;
  losses: number;
  voids: number;
  parlayWinRate: number;
  legHitRate: number;
  roi: number;
  byStatType: Record<string, StatPerformance>;
}
```

---

## 4. Discoveries & Future Exploration

### 4.1 Data Integrity Issues to Fix

| Issue | Priority | Solution |
|-------|----------|----------|
| Player name mismatches | HIGH | Enhance fuzzy matching, add aliases table |
| Threes props voiding | HIGH | Debug settlement for FG3M stat |
| High void rate (25.7%) | HIGH | Investigate DNP patterns, improve filtering |
| Missing players in nba_api | MEDIUM | Add fallback to ESPN/other sources |

### 4.2 Prop Types Analysis

| Stat Type | Sample | Hit Rate | Recommendation |
|-----------|--------|----------|----------------|
| Points | 23 legs | **81%** | ⭐ Focus here |
| Assists | 45 legs | 75% | ⭐ Primary target |
| Rebounds | 31 legs | 72% | ✅ Include |
| PRA | 3 legs | 33% | ⚠️ Needs more data |
| Threes | 3 legs | 0% (void) | ❌ Fix settlement |

**Recommendation**: Focus on Points, Assists, Rebounds. Skip PRA and Threes until data improves.

### 4.3 Dedicated Stat Pipeline Opportunities

1. **Pace-Adjusted Projections**
   - Current: Raw averages
   - Opportunity: Adjust for game pace (possessions per game)
   - Expected impact: +3-5% accuracy

2. **Defender Matchup Data**
   - Current: Team-level DEF_RTG only
   - Opportunity: Individual defender assignments
   - Challenge: Requires play-by-play data

3. **Rotation/Lineup Intelligence**
   - Current: No lineup awareness
   - Opportunity: Track who's on court together
   - Challenge: Requires real-time lineup data

4. **Historical Prop Accuracy**
   - Current: No tracking of sportsbook accuracy
   - Opportunity: Track which books have "soft" lines
   - Expected impact: +2-3% edge identification

### 4.4 Model Weights Not Yet Considered

| Factor | Current | Potential Impact |
|--------|---------|------------------|
| **Line movement** | Not tracked | Could indicate sharp money |
| **Time of day** | Not used | Late games have different dynamics |
| **Days rest** | Partial (B2B only) | Full rest days could be predictive |
| **Season phase** | Not used | Early vs late season patterns |
| **Rivalry games** | Not tracked | Intensity affects performance |
| **Betting volume** | Not available | Would need additional data source |

### 4.5 Direction Imbalance

| Direction | Count | Hit Rate | Concern |
|-----------|-------|----------|---------|
| OVER | 70 legs | 71% | Model leans OVER heavily |
| UNDER | 8 legs | 100% | Small sample, may be overfitting |

**Investigation needed**: Why does the model favor OVER 9:1? This could indicate:
- Signal calculation bias toward positive direction
- NBA props systematically set low by books
- Or genuine market inefficiency

---

## 5. Production Readiness Checklist

### Phase 1: Validation (Current)
- [ ] Backtest 100+ more parlays
- [ ] Fix threes settlement bug
- [ ] Improve player name matching
- [ ] Test on regular season games
- [ ] Document all edge cases

### Phase 2: Infrastructure
- [ ] Create Dockerfile
- [ ] Create railway.toml
- [ ] Set up cron jobs
- [ ] Add health checks
- [ ] Set up logging/alerting

### Phase 3: API Layer
- [ ] Build FastAPI/Flask endpoints
- [ ] Add authentication
- [ ] Create OpenAPI documentation
- [ ] Rate limiting

### Phase 4: Frontend
- [ ] Define component library
- [ ] Create parlay card design
- [ ] Build dashboard
- [ ] Mobile responsive

### Phase 5: Go-Live
- [ ] Paper trading period (2-4 weeks)
- [ ] Gradual rollout with limits
- [ ] Monitoring dashboard
- [ ] Kill switch capability

---

## 6. Conclusion

**The 59.3% parlay win rate is promising but not yet trustworthy.**

Key concerns:
1. Sample too small (need 3.5x more data)
2. High void rate masking issues
3. OVER/UNDER imbalance needs investigation
4. Missing infrastructure for production

Recommended next steps:
1. **Immediate**: Fix player matching, debug threes settlement
2. **Short-term**: Backtest Dec 2025 regular season games
3. **Medium-term**: Build production infrastructure
4. **Long-term**: Explore pace-adjusted projections pipeline

The correlation signal optimization (5% → 20%) appears valid based on points prop improvement (56% → 81%), but we need more data to confirm this isn't noise.
