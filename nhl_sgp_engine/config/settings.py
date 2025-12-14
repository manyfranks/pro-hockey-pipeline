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

# Signal Weights (matching NCAAF pattern with NHL adaptations)
SIGNAL_WEIGHTS = {
    'line_value': 0.35,      # Season avg vs prop line (primary)
    'trend': 0.15,           # Recent form vs season
    'usage': 0.10,           # TOI/PP changes
    'matchup': 0.15,         # Goalie quality, team defense
    'environment': 0.15,     # B2B, rest, travel
    'correlation': 0.10,     # Game total/spread impact
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
