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
# With 5 markets, 1 region: 50 calls per game
# 3000 / 50 = 60 games (acceptable for validation)
BACKTEST_MARKETS = [
    'player_points',           # Our primary model output (6.7% predictive value)
    'player_shots_on_goal',    # Validated in Nov-Dec 2025 backtest (48.6% hit rate)
    'player_goals',            # High-value prop (NOTE: 0.5 lines structurally biased)
    'player_assists',          # Playmaker analysis
    'player_total_saves',      # Goalie saves - NEW signal added Dec 18, 2025
]

# ALL markets for production (independent SGP engine per MULTI_LEAGUE_ARCHITECTURE.md)
# REQUIRES: EdgeCalculator(contrarian_threshold=15.0) for optimal results
# Backtest: Dec 18, 2025 - 52,106 props (excl. goals) - 60.6% contrarian hit rate
PRODUCTION_MARKETS = [
    'player_points',           # Points O/U - VALIDATED (50.3%, 60.6% contrarian)
    'player_assists',          # Assists O/U - VALIDATED (64.1% contrarian)
    'player_shots_on_goal',    # SOG O/U - VALIDATED (51.0%)
    'player_total_saves',      # Goalie saves - VALIDATED (63.2% negative edge)
    # NOTE: player_goals EXCLUDED - 0.5 lines are structurally biased (97.5% UNDER)
]

# Markets by tier (for budget management)
TIER1_MARKETS = ['player_points']  # Validated, primary focus
TIER2_MARKETS = ['player_shots_on_goal', 'player_assists', 'player_total_saves']  # High volume
TIER3_MARKETS = ['player_blocked_shots']  # Lower priority

# Game-level markets (separate workflow from player props)
# NOTE: Game totals use GameTotalsSignal for expected total calculation
# Fetched via /v4/sports/{sport}/odds (not player props endpoint)
# VALIDATED Dec 18, 2025: 87.5% hit rate at 10-15% edge (FOLLOW model direction!)
GAME_LEVEL_MARKETS = ['totals', 'spreads', 'h2h']

# Game totals production filters (validated Dec 18, 2025 - 364 games)
# KEY INSIGHT: Game totals show OPPOSITE behavior to player props
# Higher edge = BETTER outcomes (no contrarian needed!)
GAME_TOTALS_OPTIMAL_EDGE = (10.0, 15.0)  # 87.5% hit rate bucket
GAME_TOTALS_MIN_EDGE = 5.0               # Minimum edge to consider

# WARNING: player_goals at 0.5 lines should be excluded from SGP
# - The market is structurally biased (most players don't score every game)
# - UNDER hits 97.5% of the time regardless of model
# - Including it inflates hit rates but doesn't represent true model accuracy

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
    # Game-level markets (not player props)
    'totals': 'totals',           # Game total O/U
    'spreads': 'spreads',         # Puck line
    'h2h': 'moneyline',           # Moneyline
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
