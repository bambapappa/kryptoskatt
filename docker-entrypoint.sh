#!/bin/sh
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting server..."
# WEB_CONCURRENCY defaults to 1: the rate limiter and background job manager
# are in-process. Scale out with multiple containers + sticky sessions instead
# of multiple workers, or accept per-worker state.
# FORWARDED_ALLOW_IPS: set to your reverse proxy's IP/CIDR so X-Forwarded-*
# headers are only trusted from it (never "*" on a public network).
exec uvicorn kryptoskatt.web.app:app \
    --host 0.0.0.0 --port 8000 \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
