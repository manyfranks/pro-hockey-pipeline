Here is a **full ADR (Architecture Decision Record/Reference)** for your application, leveraging all relevant NHL endpoints from SportsDataIO. This is designed for developer handoff and technical planning.

***

**NHL Starting Lineup Confidence Application: Full Endpoints Map**

**I. Schedules and Matchups (Daily Game Slate)**
- `/v3/nhl/scores/json/GamesByDate/{date}`: All games, teams, times, statuses for a specified date
- `/v3/nhl/scores/json/ScoresBasic/{date}`: Lightweight schedule, basic matchup list

**II. Teams and Rosters**
- `/v3/nhl/scores/json/PlayersByActive`: All active NHL players (with injuries/scratches if available)
- `/v3/nhl/scores/json/PlayersBasic/{team}`: Roster for any given team
- `/v3/nhl/scores/json/AllTeams`: Full team reference, metadata
- `/v3/nhl/scores/json/teams`: Only active teams

**III. Projected Starters (Pregame)**
- SportsDataIO does **not have an explicit NHL “ProjectedLineups” endpoint** for skaters, but:
  - Use `/PlayersByActive`, `/PlayersBasic/{team}`, latest team news/reports to project probable starters/lines
  - For goalies, check `/PlayerNews/{playerid}` and update with game day announcements for projected starter

**IV. Player and Team News (Injury, Scratch, Starting Goalie Updates)**
- `/v3/nhl/scores/json/PlayerNews/{playerid}`
- `/v3/nhl/scores/json/PlayerGameStatsBySeason/{season}/{playerid}/{numberofgames}`: Recent game logs for projection logic
- `/v3/nhl/scores/json/PlayerSeasonStatsByTeam/{season}/{team}`: Summary context for a player’s season trends

**V. Game Stats and Postgame Calibration**
- `/v3/nhl/stats/json/BoxScoresFinal/{date}`: Official final box scores for all games—ground truth for model calibration
- `/v3/nhl/stats/json/BoxScoreFinal/{gameid}`: Single game box score
- `/v3/nhl/stats/json/PlayerGameStatsByDateFinal/{date}`: Final player-level stats for every participant

**VI. Utility/Supporting Endpoints**
- `/v3/nhl/scores/json/CurrentSeason`: Identify current season
- `/v3/nhl/scores/json/Standings/{season}`: Team standings for contextual analytics
- `/v3/nhl/scores/json/Stadiums`: Venue metadata for additional context
- `/v3/nhl/scores/json/AreAnyGamesInProgress`: Game day operational support

***

**Application Workflow Outline**

1. **Early AM:** Fetch games for the day (`GamesByDate`), fetch team rosters (and latest injuries/scratches).
2. **Pregame:** Project lineup using a combination of:
    - Recent games played (game logs, box scores)
    - Injury/news/scratch feeds
    - Goalies: project with high confidence if announced or tracked via news endpoints.
3. **Confidence Assignment:** Use historical accuracy, injury status, last-game participation (from box scores), and news reporting to calibrate the probability/confidence of each projected starter.
4. **After Games:** Fetch box scores and player stats. Update next-day confidence by comparing projected vs. actual starters.
5. **Continuous:** Use standings, player logs, and context feeds for deeper modeling and long-term calibration.

***

**Data Model (ERD - Key Entities)**
| Entity         | Purpose                                     | Sample Fields                                    |
|----------------|---------------------------------------------|--------------------------------------------------|
| Game           | Daily matchup info                          | game_id, date, teams, venue                      |
| Team           | Team reference info                         | team_id, name, conference, active                |
| Player         | Player metadata                             | player_id, name, position, team                  |
| ProjectedLineup| Daily projected starter list                | game_id, team_id, player_id, confidence, source  |
| PlayerNews     | Injury/scratch/context for projection logic | player_id, news_type, effective_date             |
| ActualLineup   | Final postgame verified starter list        | game_id, player_id, minutes_played, statline     |

***

**Sample Use Cases**
- **Matchups & Planning:** Schedule scraping and daily lineup prediction for fantasy, betting, analytics.
- **Pregame Projections:** High-confidence goalie starter, plus projected skater lines (with dynamic confidence per player).
- **Model Calibration:** Retrospective correction using box scores (who played and why), refining projections daily.

***

**Technical Implementation Recommendations**
- **All endpoints are GET + require API key.**
- **Call interval:** filter by endpoint (most allow every 1–60 minutes).
- **Combine projected, reported, and actual endpoints for both pregame projections and postgame calibration loop.

***

**Handoff Instructions**
- Use the above endpoint map and ERD as a *reference for API integration, data modeling, and system workflow.*
- Calibrate confidence values using historical endpoint returns and real-world injury/scratch/news information.

If you need the actual endpoint URLs or a JSON schema example for any entity, request specifics and I’ll generate them!

[1](https://sportsdata.io/developers/api-documentation/nhl)

---

**Additional Context**

Based on a deep dive into **the NHL API Workflow Guide from SportsDataIO**, you can make your application's ADR even more comprehensive by explicitly leveraging these additional endpoints, best practices, and nuanced data feeds—some of which are unique and only fully explained in the workflow documentation.

***

## Deep Workflow Insights & Improvements

### 1. **Depth and Line Combinations**

- **Goalie Depth Charts**
  - `/v3/nhl/scores/json/DepthCharts_Goalies`
    - Use for ranking goalies by team, seeing rotation patterns and identifying likely/preferred starter when not formally announced yet.
- **Starting Goaltenders**
  - `/v3/nhl/scores/json/StartingGoaltendersByDate/{date}`
    - Combines projected and confirmed starters, updating after team announcement and morning skate. Use this for your confidence model on goaltenders.
- **Line Combinations**
  - `/v3/nhl/scores/json/LineCombinationsBySeason/{season}`
    - Use for the most recent forward and defense combinations for every team. These are not always "official" starters, but they're vital for projections.
    - **Key metadata:** LineType (EV, PP…), LineNumber, and historical combinations for recognizing team patterns.

### 2. **Injury and Transaction Real-Time Monitoring**

- **Injuries**
  - `/v3/nhl/scores/json/PlayerDetailsByInjured`
    - Complete and *current* injured list (both IR and day-to-day), robust for scratch/inactive/injury decision modeling.
  - `InjuryStatus`/`InjuryNote` fields
    - Combine coded status with the written note (can often reveal return dates or context not available in structured fields).
- **Transactions**
  - `/v3/nhl/scores/json/Transactions`
    - Captures all trades, assignments, call-ups, and scratches. Running this daily helps adjust projected lineups instantly as news drops.

### 3. **Rosters and Team/Player Metadata**

- **Players by Active, Team, Free Agent, Injured, etc.**
  - Refresh frequently for call-ups/demotions and last-minute scratches.
- **AllTeams, TeamProfiles (Active/All/Season)**
  - Use to generate your internal team reference, align with venue/stadium changes, and join with line and roster logic.

### 4. **Gameday Operations and Scoring**

- **Gameday Schedule & Game State**
  - Use `/GamesByDate`, `/GamesBasicByDate`, `/GamesByDateLiveFinal` for regular polling (pre, live, and post).
- **Game State and Periods**
  - Track "Status" fields and period/clock for supporting live dashboards or verifying if a player ended up scratched late.

### 5. **Player & Team Statistics**

- **Box Scores, Player/Team Game/Season Stats**
  - `/BoxScoresByDate{date}` (Live & Final) for retroactive confirmation.
  - `/PlayerGameStatsBySeason`, `/PlayerGameStatsByDateFinal` for advanced projection logic.

### 6. **Betting Data (Optional)**
If your application integrates odds or player/game props:
- Leverage odds (pregame/live), props, and event endpoints for additional context and confidence signals.

### 7. **Other Supporting Feeds**
- **Stadiums**: `/Stadiums`
- **Standings**: `/Standings` (contextual, for modeling coach decisions in playoff push)
- **News**: `/PlayerNews/{playerid}`

***

## Crystalizing the Workflow

With the above, your ADR should state:

1. **Daily Matching:**
   - Pull schedule, current rosters, depth charts, and recent line combos.
   - Combine injuries, transactions, depth data, and starter announcements for goalies.
2. **Projection Engine:**
   - Project likely lines/starters based on line combos, health, news, and depth order.
   - Assign confidence from source recency (confirmed > projected > depth chart order).
3. **Postgame Model Calibration:**
   - Fetch final box scores, match predictions to reality, adjust future model weights accordingly.
4. **Continuous Update:**
   - Monitor transaction/injury/news endpoints and update projections within minutes of new info.

***

## In Summary

- The **Workflow Guide confirms and expands** that box scores, transactions, depth charts for goalies, line combos for projected skater groupings, and robust injury/transaction monitoring are all vital for the most accurate, up-to-date morning projections.
- **Use all endpoints with fastest-allowed polling (some as quickly as every 1 minute)**, especially before lineup lock, for best real-time model.
- The workflow page validates including confidence logic based on all available news, not just historical starts.

**You now have the most comprehensive plan possible using SportsDataIO’s NHL API. If you need a full listing of endpoints by method/return, or a sample openAPI spec, I can generate that too.**

[1](https://sportsdata.io/developers/workflow-guide/nhl)

