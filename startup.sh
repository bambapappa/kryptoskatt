#!/bin/sh
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting web server..."
exec kryptoskatt serve --host 0.0.0.0 --port 8000
