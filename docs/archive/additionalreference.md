Based on the **NHL Data Dictionary** deep dive, here are additional **high-value endpoints and data objects** your dev team should leverage to maximize prediction accuracy for “who will score at least one point”:

***

### 1. **Play-by-Play & Detailed Scoring Data**
- **`/PlayByPlay/{gameid}`** and **`/Play/{gameid}`**
  - Full event log for each game: *Who scored each goal, who assisted, which goalie was in net, down to the exact period, time, and situation*.
  - **Critical** for BvP (skater vs goalie) analysis, and for factoring in power play, even strength, and situational stats.
  - **Fields:** Goal scorer, 1st and 2nd assists, Goalie on ice, strength (PP/SH/EV), period, time, opponent.

### 2. **Matchup Trends & Team Trends**
- **`/MatchupTrends`**
  - Historical results and trends between any two teams: *Team defensive performance, PK/PP efficiency, home/away, recent streaks vs. specific opponents*.
  - Can be used to build momentum and matchup models.

### 3. **Line Combinations**
- **`/LineCombinationsBySeason/{season}`**
  - See current and historical lines, which is key for projecting assists (who plays with whom—correlated point production).
  - *Top line, PP1, even strength, etc.*

### 4. **Depth Charts & Confirmed Starters**
- **`/DepthCharts_Goalies`**
- **`/StartingGoaltendersByDate/{date}`**
  - Detect callups, backups, and goalie changes, crucial for “targeting” weak netminders.

### 5. **DFS Player Feeds**
- **`/DfsSlatePlayers`** and **`/DfsSlatePlayer`**
  - Player eligibility, salary, expected playing role for the DFS slates.
  - Sometimes DFS projections include implied role or late-scratch indicators.

### 6. **Betting Markets & Props**
- **`/BettingPlayerPropsByGame/{gameid}`**  
- **`/BettingMarkets`**, **`/BettingOutcomes`**
  - Consensus and sportsbook-specific odds on player points/goals/assists. Real-money betting lines are market-based “expected probabilities”—useful as a reality check for your model outputs.

### 7. **Period & Situation Splits**
- Play-by-play (above) includes **strength** (EV/PP/SH), so you can analyze:
  - Points by period, on the power play, short-handed, game situation (trailing, leading).

### 8. **Team Allowed Stats by Position**
- **`/TeamStatsAllowedByPosition/{season}`**
  - How many goals/assists/points allowed by each team to each position type (C, LW, RW, D).
  - Use to target weak defenses against specific types of players.

***

## **Summary Table of Key New/Advanced Feeds**

| Use Case                    | Endpoint(s) / Object                | Why Important                                        |
|-----------------------------|-------------------------------------|------------------------------------------------------|
| True BvP (Skater vs Goalie) | `/PlayByPlay/{gameid}`              | Assigns each point to exact goalie in net            |
| Goalie or Opponent Tracking | `/DepthCharts_Goalies`, `/StartingGoaltendersByDate` | Project matchup quality, spot backups/callups        |
| Line Correlation            | `/LineCombinationsBySeason`, `/DfsSlatePlayers`      | Who skates together, see strong linemates            |
| Momentum, Trends            | `/MatchupTrends`                    | Hot/cold streaks, team strengths/weaknesses          |
| Defense Position Weakness   | `/TeamStatsAllowedByPosition`        | Target teams that allow more to certain skater types |
| Market Odds/Props           | `/BettingPlayerPropsByGame`, `/BettingMarkets`       | Benchmark/model using oddsmaker predictions          |
| In-Depth Player/Team Stats  | `/PlayerGameLogsBySeason`, `/PlayerSeasonStats`      | Recent form, home/away splits, road trips            |

***

**Bonus:** All feeds, including injury/scratch/transaction, are already mapped in your previous ADR and workflow. *Be sure your dev team leverages all subfeeds and documentations on object fields (sometimes the best data is in object properties of a “main” endpoint!).*

If you’d like, I can produce a concrete OpenAPI-like list, schema reference, or a specific endpoint call example for any of the objects above. This should ensure you’re capturing the absolute maximum predictive and contextual data that SportsDataIO’s NHL API can offer for your point projection engine.

[1](https://sportsdata.io/developers/data-dictionary/nhl)