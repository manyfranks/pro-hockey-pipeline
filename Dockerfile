# NHL Daily Pipeline - Production Dockerfile
# Runs the daily orchestrator: Settlement -> Predictions -> Insights

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for lxml and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt1-dev \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire nhl_isolated package
COPY . /app/nhl_isolated/

# Set Python path to find the package
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create data directories
RUN mkdir -p /app/nhl_isolated/data/predictions \
             /app/nhl_isolated/data/insights \
             /app/nhl_isolated/data/cache

# Default command: run daily orchestrator for today
# Override with: docker run <image> --date 2025-11-26 --no-llm
ENTRYPOINT ["python", "-m", "nhl_isolated.scripts.daily_orchestrator"]

# Default args (can be overridden)
CMD []
