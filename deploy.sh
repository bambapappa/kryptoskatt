#!/usr/bin/env bash
# deploy.sh — Pull latest image and restart KryptoSkatt on the VPS
# Run this on the server: bash deploy.sh
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

echo "==> Pulling latest images..."
docker compose -f "$COMPOSE_FILE" pull

echo "==> Restarting services (migrations run automatically on startup)..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo "==> Waiting for health check..."
sleep 5
if curl -sf http://localhost:8000/health > /dev/null; then
    echo "✓ Service is healthy"
else
    echo "✗ Health check failed — check logs:"
    docker compose -f "$COMPOSE_FILE" logs app --tail=50
    exit 1
fi
