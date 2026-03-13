#!/bin/sh
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting server..."
exec uvicorn kryptoskatt.web.app:app --host 0.0.0.0 --port 8000 --workers 2
