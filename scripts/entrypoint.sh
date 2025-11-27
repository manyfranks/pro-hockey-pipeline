#!/bin/bash
# NHL Prediction Pipeline - Docker Entrypoint Script
#
# Usage:
#   ./entrypoint.sh              # Run predictions for today + settle yesterday
#   ./entrypoint.sh predictions  # Run predictions only
#   ./entrypoint.sh settlement   # Run settlement only
#   ./entrypoint.sh backfill START:END  # Backfill date range

set -e

# Ensure we're in the right directory
cd /app

# Default command
COMMAND=${1:-full}

echo "=============================================="
echo "NHL Prediction Pipeline"
echo "Started: $(date)"
echo "Command: $COMMAND"
echo "=============================================="

run_predictions() {
    echo ""
    echo "[PREDICTIONS] Starting prediction pipeline..."
    python3 -m pipeline.nhl_prediction_pipeline --db
    echo "[PREDICTIONS] Complete"
}

run_settlement() {
    echo ""
    echo "[SETTLEMENT] Starting settlement pipeline..."
    # Settle yesterday's predictions by default
    python3 -m pipeline.settlement
    echo "[SETTLEMENT] Complete"
}

run_backfill() {
    local date_range=$1
    if [ -z "$date_range" ]; then
        echo "[ERROR] Backfill requires date range in format START:END (e.g., 2025-10-01:2025-10-31)"
        exit 1
    fi
    echo ""
    echo "[BACKFILL] Starting backfill for $date_range..."
    python3 -m pipeline.nhl_prediction_pipeline --backfill "$date_range" --db
    echo "[BACKFILL] Complete"
}

case $COMMAND in
    full)
        run_predictions
        run_settlement
        ;;
    predictions)
        run_predictions
        ;;
    settlement)
        run_settlement
        ;;
    backfill)
        run_backfill "$2"
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Usage: entrypoint.sh [full|predictions|settlement|backfill START:END]"
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo "Pipeline finished: $(date)"
echo "=============================================="
