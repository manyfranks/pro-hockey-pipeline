"""
NHL Player Prop Market Configuration

Market keys from The Odds API for NHL player props.
https://the-odds-api.com/sports-odds-data/betting-markets.html
"""

# Primary markets (high priority for backtesting)
PRIMARY_MARKETS = [
    'player_points',              # Points O/U - maps directly to our model
    'player_goals',               # Goals O/U
    'player_assists',             # Assists O/U
]

# Secondary markets (lower priority)
SECONDARY_MARKETS = [
    'player_shots_on_goal',       # SOG O/U
    'player_blocked_shots',       # Blocks O/U
    'player_power_play_points',   # PP Points O/U
]

# Goalie markets
GOALIE_MARKETS = [
    'player_total_saves',         # Saves O/U
]

# Anytime scorer markets (like NFL ATTD)
ANYTIME_MARKETS = [
    'player_goal_scorer_anytime', # Anytime goal scorer
    'player_goal_scorer_first',   # First goal scorer
    'player_goal_scorer_last',    # Last goal scorer
]

# Alternate lines (different O/U values)
ALTERNATE_MARKETS = [
    'player_points_alternate',
    'player_goals_alternate',
    'player_assists_alternate',
    'player_shots_on_goal_alternate',
    'player_blocked_shots_alternate',
    'player_power_play_points_alternate',
    'player_total_saves_alternate',
]

# All markets combined
ALL_MARKETS = PRIMARY_MARKETS + SECONDARY_MARKETS + GOALIE_MARKETS + ANYTIME_MARKETS

# Markets to use for backtesting (budget-conscious - 3k calls)
# Cost: 10 calls per region per market per event
# With 2 markets, 1 region: 20 calls per game
# 3000 / 20 = 150 games
BACKTEST_MARKETS = [
    'player_points',    # Our primary model output
    'player_goals',     # High-value prop
]

# ALL markets for production (independent SGP engine per MULTI_LEAGUE_ARCHITECTURE.md)
PRODUCTION_MARKETS = [
    'player_points',           # Points O/U - VALIDATED (58.9% hit rate)
    'player_goals',            # Goals O/U
    'player_assists',          # Assists O/U
    'player_shots_on_goal',    # SOG O/U
    'player_blocked_shots',    # Blocks O/U
]

# Markets by tier (for budget management)
TIER1_MARKETS = ['player_points']  # Validated, primary focus
TIER2_MARKETS = ['player_shots_on_goal']  # High volume, testable with NHL API
TIER3_MARKETS = ['player_goals', 'player_assists', 'player_blocked_shots']  # Lower priority

# Stat type mapping (Odds API market -> our internal stat type)
MARKET_TO_STAT_TYPE = {
    'player_points': 'points',
    'player_goals': 'goals',
    'player_assists': 'assists',
    'player_shots_on_goal': 'shots_on_goal',
    'player_blocked_shots': 'blocked_shots',
    'player_power_play_points': 'pp_points',
    'player_total_saves': 'saves',
    'player_goal_scorer_anytime': 'anytime_goal',
    'player_goal_scorer_first': 'first_goal',
    'player_goal_scorer_last': 'last_goal',
}

# Reverse mapping
STAT_TYPE_TO_MARKET = {v: k for k, v in MARKET_TO_STAT_TYPE.items()}

# Supported bookmakers (US)
SUPPORTED_BOOKMAKERS = [
    'draftkings',
    'fanduel',
    'betmgm',
    'caesars',
    'pointsbetus',
    'bovada',
]

# Primary bookmaker for edge calculation (most liquid)
PRIMARY_BOOKMAKER = 'draftkings'
