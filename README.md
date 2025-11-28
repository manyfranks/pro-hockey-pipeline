# NHL Player Points Prediction Pipeline

A machine learning pipeline that predicts which NHL players are most likely to record at least one point (goal or assist) in their upcoming games. The system generates daily predictions, settles against actual results, and produces actionable insights for sports analytics.

## Features

- **Daily Predictions**: Generates ranked player predictions using a composite scoring algorithm
- **Automated Settlement**: Settles yesterday's predictions against actual game results
- **Multi-Source Data**: Combines NHL Official API with DailyFaceoff line combinations
- **LLM-Powered Insights**: Optional Claude/OpenAI integration for narrative analysis
- **Caching Layer**: TTL-based caching to minimize API calls
- **Docker Ready**: Containerized deployment with docker-compose

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Daily Orchestrator                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Settlement      2. Predictions       3. Insights            │
│  (Yesterday)        (Today)              (Today)                │
│       │                  │                    │                 │
│       ▼                  ▼                    ▼                 │
│  ┌─────────┐      ┌────────────┐      ┌─────────────┐          │
│  │ Box     │      │ Enrichment │      │ Rule-based  │          │
│  │ Scores  │      │ Pipeline   │      │ + LLM       │          │
│  └────┬────┘      └─────┬──────┘      └──────┬──────┘          │
│       │                 │                    │                  │
│       ▼                 ▼                    ▼                  │
│  ┌─────────────────────────────────────────────────┐           │
│  │                  PostgreSQL                      │           │
│  └─────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### Scoring Algorithm

The final prediction score (50-100) is calculated using:

| Component | Weight | Description |
|-----------|--------|-------------|
| Recent Form | 50% | Points per game over last 10 games |
| Line Opportunity | 20% | Line quality + PP1 bonus |
| Goalie Weakness | 15% | Opposing goalie's recent save percentage |
| Matchup Quality | 10% | Team defense + skater-vs-goalie history |
| Situational Factors | 5% | Back-to-back, home/away adjustments |

## Project Structure

```
pro-hockey-pipeline/
├── analytics/              # Scoring calculators and insights
│   ├── final_score_calculator.py
│   ├── recent_form_calculator.py
│   ├── line_opportunity_calculator.py
│   ├── goalie_weakness_calculator.py
│   ├── matchup_analyzer.py
│   ├── situational_analyzer.py
│   ├── insights_generator.py
│   └── llm_insights.py
├── database/               # PostgreSQL integration
│   └── db_manager.py
├── pipeline/               # Core prediction workflows
│   ├── nhl_prediction_pipeline.py
│   ├── enrichment.py
│   └── settlement.py
├── providers/              # Data source abstraction
│   ├── base.py
│   ├── nhl_official_api.py
│   ├── dailyfaceoff_scraper.py
│   └── cached_provider.py
├── scripts/                # Executable entry points
│   ├── daily_orchestrator.py
│   ├── backfill_predictions.py
│   ├── healthcheck.py
│   └── test_endpoints.py
├── utilities/              # Logging and caching
│   ├── logger.py
│   └── cache_manager.py
├── docs/                   # Documentation
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Prerequisites

- Python 3.11+
- PostgreSQL
- Docker & Docker Compose (optional)

## Installation

### Local Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/pro-hockey-pipeline.git
cd pro-hockey-pipeline
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Docker Setup

```bash
docker-compose up --build
```

## Configuration

Create a `.env` file with the following variables:

### Required

```env
DATABASE_URL=postgresql://user:password@host:5432/sports_analytics
```

### Optional

```env
# Logging
LOG_LEVEL=INFO                              # DEBUG, INFO, WARNING, ERROR

# Cache settings
DAILYFACEOFF_CACHE_TTL_HOURS=6              # Line data cache duration

# LLM Configuration (choose one provider)
OPENROUTER_API_KEY=sk-or-v1-...             # Recommended
OPENROUTER_MODEL_NAME=anthropic/claude-3.5-sonnet

# Alternative LLM providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## Usage

### Run Full Pipeline

```bash
# Local
python -m scripts.daily_orchestrator

# Docker
docker-compose up --build
```

### Command Line Options

```bash
# Run for a specific date
python -m scripts.daily_orchestrator --date 2025-11-26

# Skip LLM insights generation
python -m scripts.daily_orchestrator --no-llm

# Dry run (no database writes)
python -m scripts.daily_orchestrator --dry-run

# Force refresh cached data
python -m scripts.daily_orchestrator --force-refresh
```

### Backfill Historical Data

```bash
python scripts/backfill_predictions.py 2025-11-01 2025-11-23
```

### Health Check

```bash
python scripts/healthcheck.py
```

### Test API Endpoints

```bash
python scripts/test_endpoints.py
```

## Database Schema

| Table | Description |
|-------|-------------|
| `nhl_players` | Player metadata (name, team, position) |
| `nhl_games` | Game schedule and results |
| `nhl_daily_predictions` | Prediction records with scores and ranks |
| `nhl_settlements` | Historical prediction outcomes |

### Settlement Outcome Codes

| Code | Meaning |
|------|---------|
| 1 | HIT - Player recorded 1+ points |
| 0 | MISS - Player recorded 0 points |
| 2 | POSTPONED - Game was postponed |
| 3 | DNP - Player did not play |

## Data Sources

- **NHL Official API** (`api-web.nhle.com`): Games, rosters, player stats, box scores
- **DailyFaceoff**: Line combinations, power play units, starting goalies

## Development

### Code Quality

```bash
# Format code
black .

# Lint
flake8 .

# Type check
mypy .
```

### Testing

```bash
pytest
pytest --cov=.
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
