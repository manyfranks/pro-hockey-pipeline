"""
NHL SGP Engine Settings

Configuration for API access, thresholds, and operational parameters.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
for env_path in ['.env.local', '.env', '../.env.local', '../.env']:
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        break

# API Configuration
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
ODDS_API_BASE_URL = 'https://api.the-odds-api.com/v4'

# Database
DATABASE_URL = os.getenv('DATABASE_URL')

# NHL Sport key for Odds API
NHL_SPORT_KEY = 'icehockey_nhl'

# API Budget Management
API_BUDGET_MONTHLY = 20000  # Shared across pipelines
API_BUDGET_NHL_SGP = 3000   # Allocated for NHL SGP backfill
API_COST_HISTORICAL_EVENTS = 1
API_COST_HISTORICAL_ODDS = 10  # Per region per market

# Regions (for odds)
REGIONS = ['us']  # Focus on US books for player props

# Edge Detection Thresholds
MIN_EDGE_PCT = 5.0           # Minimum edge to consider
HIGH_EDGE_PCT = 8.0          # High-value edge threshold
ELITE_EDGE_PCT = 12.0        # Elite edge threshold

# Confidence Thresholds
MIN_CONFIDENCE = 0.60        # Minimum confidence to include
HIGH_CONFIDENCE = 0.75       # High confidence threshold

# Signal Weights (optimized based on Dec 18, 2025 backtest - 75,451 props)
# Predictive value = |positive_hit_rate - negative_hit_rate|
# NOTE: These weights are used WITH contrarian mode (threshold=15.0)
# The inverted edge relationship means signal DIRECTION matters more than magnitude
SIGNAL_WEIGHTS = {
    'environment': 0.24,     # B2B, rest, travel (61.0% predictive - HIGHEST!)
    'usage': 0.19,           # TOI/PP/line deployment (24.5% predictive)
    'line_value': 0.15,      # Season avg vs prop line (20.0% predictive)
    'matchup': 0.10,         # Goalie quality, team defense (5.1% predictive)
    'shot_quality': 0.08,    # NHL Edge API - shot speed, HD%, zone deployment (NEW)
    'goalie_saves': 0.08,    # NHL Edge API - goalie saves props (VALIDATED 63.2%)
    'game_totals': 0.08,     # Game total O/U signal (NEW - needs backtest)
    'correlation': 0.04,     # Game total/spread impact (2.8% predictive)
    'trend': 0.04,           # Recent form vs season (0.7% predictive - nearly useless)
}

# Parlay Configuration
MAX_LEGS_PER_PARLAY = 4
MIN_LEGS_PER_PARLAY = 2
MAX_CORRELATION_PENALTY = 0.15  # Reduce edge for correlated legs

# Cache Configuration
CACHE_DIR = Path(__file__).parent.parent / 'data' / 'cache'
CACHE_TTL_HOURS = 6

# Historical Data Range
# Odds API player props available from May 3, 2023
HISTORICAL_START_DATE = '2023-05-03'

# Output directories
DATA_DIR = Path(__file__).parent.parent / 'data'
BACKTEST_DIR = DATA_DIR / 'backtest'
ODDS_CACHE_DIR = DATA_DIR / 'odds_cache'

# Ensure directories exist
for dir_path in [DATA_DIR, BACKTEST_DIR, ODDS_CACHE_DIR, CACHE_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)
