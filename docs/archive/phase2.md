Here’s a comprehensive **workflow and endpoint mapping** for building a daily, ranked “most likely to score a point” list for NHL players, factoring *hot streaks, weak goalies, b2b games, roadtrips, new/callup goalies, poor defenses, power play/penalty kill stats, venue effects, and home/road splits*—all using SportsDataIO endpoints:

***

## Application Workflow

### 1. **Fetch Daily Schedule & Team Rosters**
**Endpoints:**
- `/GamesByDate/{date}`: Get the day's games
- `/PlayersProfilesByTeam/{team}`: Fetch active roster per team

### 2. **Player Hot Streaks / Recent Form**
**Endpoints:**
- `/PlayerGameLogsBySeason/{season}`: Last X games, points per game
- `/PlayerGameStatsByDateFinal/{date}`: Who’s currently hot

### 3. **Identify Opposing Goalie Weakness**
**Endpoints:**
- `/StartingGoaltendersByDate/{date}`: Confirm goalie starters
- `/DepthCharts_Goalies`: Spot callups/backups
- `/PlayerSeasonStats/{season}`: Goalie season stats (SV%, GAA, etc)
- `/PlayerGameLogsBySeason/{season}`: Goalie last X game trends

### 4. **Fatigue: B2B, Road Trips**
**Endpoints:**
- `/SchedulesBasic/{date}` + `/TeamGameLogsBySeason/{season}`: Sequence of games, days off, travel patterns

### 5. **Defensive Weakness Analysis**
**Endpoints:**
- `/TeamSeasonStats/{season}`: Goals/assists allowed, PK stats
- `/TeamStatsAllowedByPosition/{season}`: Points allowed by position (C, LW, RW, D)
- `/PlayerSeasonStatsByTeam/{season}/{team}`: Team PK/PP effectiveness

### 6. **Power Play Offense / Penalty Kill Defense**
**Endpoints:**
- `/TeamSeasonStats/{season}`: PP%/PK%
- `/PlayerSeasonStats/{season}`: Power play points, team splits

### 7. **Venue/Home/Road Splits, Historical Venue Stats**
**Endpoints:**
- `/PlayerGameLogsBySeason/{season}`: Home/away/venue splits (filter by field)
- `/Stadiums`: Stadium metadata/context

### 8. **Line Combinations & High Correlation Skaters**
**Endpoints:**
- `/LineCombinationsBySeason/{season}`: Likely teammates for points correlation (who’s centering hot wings?)

### 9. **Injuries/Scratches/Transactions**
**Endpoints:**
- `/PlayerDetailsByInjured`: Filter out “Out”/“Questionable”
- `/Transactions`: Recent callups, demotions, fresh line changes

### 10. **Integrate Betting/Props Data (Optional Enhancement)**
**Endpoints:**
- `/BettingPlayerPropsByGame/{gameid}`: Compare sportsbook probabilities/lines for “player to score a point”

***

## Data Modeling & Ranking Logic

- **Calculate for each player:**
  - **Recent points/game** (hot streak)
  - **Opponent goalie stats/trends** (weakness/callup)
  - **Opposing team defensive stats** (bad PK/GA/points allowed)
  - **Back-to-back, road trip/fatigue modifier**
  - **Team's PP strength vs opponent PK weakness**
  - **Home/road/venue history**
  - **Line combo stability**
  - **Injury/news/scratch status**
  - **Sportsbook odds (optional confidence calibration)**

- **Output:**  
  - Ranked list: player_id, name, team, matchup, point probability/confidence, reasoning factors (hot streak, bad goalie, etc)

***

## Example Pseudocode Flow

```python
games = fetch('/GamesByDate/{date}')
for game in games:
    home_team, away_team = game['Teams']
    goalie = fetch('/StartingGoaltendersByDate/{date}')
    for team in [home_team, away_team]:
        roster = fetch('/PlayersProfilesByTeam/{team}')
        for player in roster:
            # Key Factors
            streak_score = get_recent_form(player, '/PlayerGameLogsBySeason')
            goalie_score = get_goalie_weakness(game, '/StartingGoaltenders', '/PlayerSeasonStats')
            fatigue_score = get_fatigue(game, '/TeamGameLogsBySeason')
            defense_score = get_defense_weakness(opp_team, '/TeamStatsAllowedByPosition')
            pk_pp_score = get_pp_pk_matchup(team, opp_team, '/TeamSeasonStats')
            venue_score = get_venue_split(player, game, '/PlayerGameLogsBySeason')
            line_score = get_line_combo_factor(player, '/LineCombinationsBySeason')
            injury_score = get_injury_status(player, '/PlayerDetailsByInjured', '/Transactions')
            prop_score = get_betting_prob(player, game, '/BettingPlayerPropsByGame')
            # Weighted composite score
            final_rank_score = weighted_sum([streak_score, goalie_score, ...])
            add_to_ranked_list(player, final_rank_score)
# Output ranked list descending by final_rank_score
```

***

## Endpoint Reference Table

| Factor/Dataset        | Endpoint(s)                                         |
|-----------------------|-----------------------------------------------------|
| Schedule              | `/GamesByDate`, `/SchedulesBasic`                   |
| Roster                | `/PlayersProfilesByTeam`                            |
| Hot Streaks           | `/PlayerGameLogsBySeason`, `/PlayerGameStatsByDateFinal` |
| Goalie Info           | `/StartingGoaltendersByDate`, `/DepthCharts_Goalies`, `/PlayerSeasonStats` |
| B2B/Road Trip         | `/SchedulesBasic`, `/TeamGameLogsBySeason`          |
| Defense/PK Weakness   | `/TeamSeasonStats`, `/TeamStatsAllowedByPosition`   |
| PP/PK Matchup         | `/TeamSeasonStats`, `/PlayerSeasonStatsByTeam`      |
| Venue/Location Splits | `/PlayerGameLogsBySeason`, `/Stadiums`              |
| Line Combinations     | `/LineCombinationsBySeason`                         |
| Injuries/Transactions | `/PlayerDetailsByInjured`, `/Transactions`          |
| Betting Props         | `/BettingPlayerPropsByGame`                         |

***

**With these APIs, you can automate ranking and probability analysis for NHL point scorers using all your target contextual and matchup factors—all directly from SportsDataIO feeds.** Let me know if you want example scoring weights, more detailed logic, or a proto schema for output!

[1](https://sportsdata.io/developers/workflow-guide/nhl)

---

**Additional Context**

It is **possible to build a “Batter vs Pitcher”-style (BvP) analysis for NHL players vs goalies**—i.e., how well a skater has scored (goals/assists/points) against a specific goalie—using SportsDataIO **with some caveats and extra processing**:

***

## What’s Possible with SportsDataIO Endpoints

**1. Player Game Logs — Opponent Metadata**
- `/PlayerGameLogsBySeason/{season}`
  - Returns detailed stats for each player game, including opponent team, goals, assists, and other stats **for every game played**.
  - **Limitation**: This does *not* natively tell you which goalie(s) faced.

**2. Game/Box Score Details — Goalie Participation**
- `/BoxScoreFinal/{gameid}` or `/BoxScoresFinal/{date}`
  - Provides all player stats per game, including each goalie’s stats for that game and all skater stats.
  - Tie a player’s game log (goal, assist) to the gameid, and the goalie(s) who played for the opposing team by matching game/gameid.

***

## How to Build Skater vs Goalie Splits

1. **Fetch All Relevant Player Game Logs**  
   - For each skater, collect game logs across all seasons or a target span.
2. **For Each Game with a Goal or Assist:**
   - Note the gameid, date, and opposing team.
3. **Use Box Score for Each Game:**
   - Identify which goalie(s) played for the opponent. Most games only have one, but some feature both (e.g., if there was a goalie change).
   - If both goalies played, advanced logic is needed to assign goals/assists to the correct goalie (based on periods/time on ice from the play-by-play, not available at this API granularity).
4. **Aggregate Stats:**
   - For each goalie and skater matchup, collect:
     - Games faced
     - Goals scored (primary for goalies who started/played)
     - Assists recorded (same logic)
   - Produce a matchup table: Player X vs Goalie Y — total goals, assists, games played.

***

## Limitations and Notes

- You cannot always precisely determine which goalie was in net for *each individual goal* without full shift/play-by-play data (which SportsDataIO may not fully provide). When only one goalie appeared for a team, mapping is exact.
- For games with two goalies, you can still quantify “Player had 2 goals when Goalie Z’s team was facing him, and Goalie Z played in that game,” but not 100% which goalie was in net for which tally.
- This approach does allow you to say “Historically, Player X has X points in games where he’s faced Goalie Y,” which is a strong BvP-style stat.

***

## Summary Table

| Endpoint               | Purpose                                    |
|------------------------|--------------------------------------------|
| PlayerGameLogsBySeason | Skater game-by-game scoring details        |
| BoxScoreFinal/BoxScoresFinal | Goalie participation per game          |

***

**Yes—you can compute this BvP-style stat within the *granularity* supported by SportsDataIO. For most analytics/betting/Fantasy scenarios, this is enough to meaningfully quantify “skater success rate facing specific goalies.”**

[1](https://sportsdata.io/developers/workflow-guide/nhl)