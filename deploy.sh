#!/usr/bin/env bash
# deploy.sh: update KryptoSkatt on the server to the latest main and restart.
# Run on the server from the repo directory: bash deploy.sh
# Migrations and the inactive-account purge run automatically at start-up.
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.yml)
[ -f docker-compose.prod.yml ] && [ "${KS_PROD:-1}" = "1" ] && COMPOSE+=(-f docker-compose.prod.yml)

echo "==> Backing up database first..."
./deploy/backup.sh || { echo "Backup failed, aborting"; exit 1; }

echo "==> Fetching latest code..."
git pull --ff-only

echo "==> Building and restarting..."
"${COMPOSE[@]}" up -d --build --remove-orphans

echo "==> Waiting for health check..."
for i in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" 2>/dev/null; then
        echo "✓ Service is healthy"; exit 0
    fi
    sleep 2
done
echo "✗ Health check failed — recent logs:"
"${COMPOSE[@]}" logs app --tail=50
exit 1
