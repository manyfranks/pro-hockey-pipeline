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

# Copy the entire package
COPY . /app/

# Set Python path to find the package
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create data directories
RUN mkdir -p /app/data/predictions \
             /app/data/insights \
             /app/data/cache

# Default command: run daily orchestrator for today
# Override with: docker run <image> --date 2025-11-26 --no-llm
ENTRYPOINT ["python", "-m", "scripts.daily_orchestrator"]

# Default args (can be overridden)
CMD []
