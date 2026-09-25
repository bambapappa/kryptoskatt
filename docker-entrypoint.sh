#!/bin/sh
set -e
echo "Running database migrations..."
alembic upgrade head
# Storage limitation (GDPR art. 5.1 e): remove long-unused accounts on every
# start. Also schedule `kryptoskatt purge-inactive` daily (cron) on the host.
kryptoskatt purge-inactive || echo "purge-inactive failed (continuing)"
echo "Starting server..."
# WEB_CONCURRENCY defaults to 1: the rate limiter and background job manager
# are in-process. Scale out with multiple containers + sticky sessions instead
# of multiple workers, or accept per-worker state.
# FORWARDED_ALLOW_IPS: set to your reverse proxy's IP/CIDR so X-Forwarded-*
# headers are only trusted from it (never "*" on a public network).
# Access logs are off by default: they would store client IPs and share-link
# tokens. Set ACCESS_LOG=true to enable.
ACCESS_LOG_FLAG="--no-access-log"
if [ "${ACCESS_LOG:-false}" = "true" ]; then ACCESS_LOG_FLAG="--access-log"; fi
exec uvicorn kryptoskatt.web.app:app \
    --host 0.0.0.0 --port 8000 \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    "$ACCESS_LOG_FLAG"
