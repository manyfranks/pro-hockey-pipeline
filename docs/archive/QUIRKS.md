# NHL SportsDataIO Data Quirks

**Last Updated:** 2025-11-24
**Based on:** Phase 0-4 implementation and testing

---

## Endpoint Validation Results (Phase 0)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `games_by_date` | **7 games** | Working |
| `scores_basic` | **7 games** | Working |
| `starting_goaltenders` | **0 items** | Timing dependent - call closer to game time |
| `goalie_depth_charts` | **Empty** | 404/Empty - use roster + stats fallback |
| `team_roster` | **57 players** | Working |
| `active_players` | **1834 players** | Working |
| `all_teams` | **41 teams** | Working |
| `line_combinations` | **404** | Not available for current season |
| `player_season_stats` | **889 players** | Working (scrambled data) |
| `player_game_logs` | **5 games** | Working (uses /stats/ path) |
| `team_season_stats` | **32 teams** | Working |
| `standings` | **32 teams** | Working |
| `box_scores_final` | **6 games** | Working |
| `injuries` | **404** | Use roster InjuryStatus field instead |
| `transactions` | **404** | Monitor roster changes instead |
| `stadiums` | **84 stadiums** | Working |
| `current_season` | **1 item** | Working |
| `are_games_in_progress` | **boolean** | Working |

---

## 1. Scrambled Data (Free Trial)

**CRITICAL:** Free trial accounts receive "scrambled" data where statistical values are randomly adjusted by 5-20% from actual values.

**Evidence from sample response:**
```json
{
  "Name": "Viktor Arvidsson",
  "Goals": 10.1,        // Should be integer
  "Assists": 11.4,      // Should be integer
  "ShotsOnGoal": 87.7,  // Should be integer
  "PlusMinus": 2.8      // Should be integer
}
```

### Why This Is Acceptable for Development

Despite the variance, scrambled data **preserves player tier classification**:

| Actual PPG | Variance Range (-20% to +20%) | Player Tier | Tier Preserved? |
|------------|-------------------------------|-------------|-----------------|
| 1.5 | 1.2 - 1.8 | Elite | ✅ Yes |
| 1.0 | 0.8 - 1.2 | High-scoring | ✅ Yes |
| 0.5 | 0.4 - 0.6 | Average | ✅ Yes |
| 0.2 | 0.16 - 0.24 | Depth | ✅ Yes |
| 0.0 | 0.0 | Non-scorer | ✅ Yes |

**Key Insight:** A 20% variance on `recent_form` (50% weight) translates to only ~10% impact on final score due to multi-component dilution.

### Where Variance Doesn't Matter

1. **Binary Outcome Prediction**: We predict "will score a point" vs "won't score a point"
   - A player showing 0.8 PPG (even if true is 1.0) is still "likely to score"
   - A player showing 0.16 PPG (even if true is 0.2) is still "unlikely to score"

2. **Relative Rankings**: If all players have similar variance, relative ordering is preserved

3. **Confidence Tiers**: Players with limited data already get lower confidence

### Where Variance Could Matter (Edge Cases)

- Players exactly at tier boundaries (e.g., 0.6 PPG ± 20% = 0.48-0.72)
- Affects ~5-10% of players
- Impact: Minor ranking shuffles, not systematic errors

**Impact:**
- Settlement logic must use rounding (e.g., `round(goals) >= 1`)
- Analysis scores naturally absorb ~10% variance through multi-component weighting
- Paid subscription recommended for production calibration/settlement

---

## 2. Season Format

The API uses the END year for season identification:
- 2024-25 season = `"2025"`
- 2025-26 season = `"2026"`

**Current Season Response:**
```json
{
  "Season": 2026,
  "StartYear": 2025,
  "EndYear": 2026,
  "Description": "2025-26"
}
```

---

## 3. Endpoint Availability Issues

### 3.1 Line Combinations - 404 for Current Season
**Endpoint:** `/v3/nhl/scores/json/LineCombinationsBySeason/{season}`

**Issue:** Returns 404 for season "2026" (current season).

**Workaround:**
- Try previous season ("2025") for historical data
- May need to use roster + recent game participation to infer lines
- Consider alternative data source for line combinations

### 3.2 Goalie Depth Charts - Empty Response
**Endpoint:** `/v3/nhl/scores/json/DepthCharts_Goalies`

**Issue:** Returns empty array or error.

**Workaround:**
- Use team roster + goalie season stats to infer depth
- Look at `Games` and `Started` fields to determine starter vs backup

### 3.3 Injuries - 404 Error
**Endpoint:** `/v3/nhl/scores/json/PlayerDetailsByInjured`

**Issue:** Returns 404 error.

**Workaround:**
- Check player roster for `InjuryStatus` field
- Use player news endpoint for injury updates

### 3.4 Transactions - 404 Error
**Endpoint:** `/v3/nhl/scores/json/Transactions`

**Issue:** Returns 404 error.

**Workaround:**
- Monitor roster changes between days
- Use player news for callup/demotion alerts

### 3.5 Starting Goaltenders - Timing Dependent
**Endpoint:** `/v3/nhl/scores/json/StartingGoaltendersByDate/{date}`

**Issue:** May return empty if called too early in the day.

**Expected Behavior:**
- Data typically available 30-60 minutes before puck drop
- Call closer to game time for best results
- Use goalie depth + recent starts as fallback

---

## 4. Box Score Structure

Box scores contain rich scoring play data:

```json
{
  "ScoringPlays": [
    {
      "ScoredByPlayerID": 33062840,
      "AssistedByPlayerID1": 33064537,
      "AssistedByPlayerID2": 33065529,
      "PowerPlay": true,
      "ShortHanded": false,
      "EmptyNet": false,
      "AllowedByTeamID": 11  // Note: Team, not Goalie
    }
  ]
}
```

**Key Observation:**
- `AllowedByTeamID` is provided, NOT `AllowedByGoalieID`
- Must cross-reference with `PlayerGames` to find goalie on ice
- This affects Skater-vs-Goalie (SvG) attribution logic

---

## 5. Player ID Format

Player IDs follow the format `3xxxxxxx` (8 digits starting with 3):
- Example: `30002576` (Connor McDavid)
- Example: `33062840` (from box score)

**Note:** Player IDs in box scores use a different range (33xxxxxx) vs roster (30xxxxxx). Need to verify mapping.

---

## 6. Position Codes

Standard position codes used:
- `C` - Center
- `LW` - Left Wing
- `RW` - Right Wing
- `D` - Defenseman
- `G` - Goaltender

---

## 7. Team Abbreviations

Standard 3-letter codes (e.g., `EDM`, `TOR`, `NYR`, `BUF`, `CAR`).

Full list available from `/v3/nhl/scores/json/AllTeams`.

---

## 8. Recommendations

1. **For Development:**
   - Use rounded values for all counts (goals, assists, etc.)
   - Build fallback logic for missing endpoints
   - Cache aggressively to reduce API calls

2. **For Production:**
   - Upgrade to paid SportsDataIO subscription
   - Implement retry logic for timing-dependent endpoints
   - Consider supplementary data sources for:
     - Line combinations
     - Real-time injuries
     - Transaction alerts

3. **For Settlement:**
   - Always use final box scores (not live)
   - Round all point values: `point_outcome = 1 if round(goals + assists) >= 1 else 0`
   - Track `IsClosed` flag before settling
