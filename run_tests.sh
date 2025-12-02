#!/bin/bash
# Script to run tests easily

set -e

echo "Running tests..."
echo "================================"

# Run integration tests (these work best)
# The test fixture will automatically read SECRET_TOKEN from /app/.env in the container
echo ""
echo "Running integration tests (against running API)..."
echo "Note: Tests will read SECRET_TOKEN from /app/.env in the container"
echo ""

docker compose exec assets-bucket python -m pytest tests/test_integration.py -v

echo ""
echo "================================"
echo "Test run complete!"

