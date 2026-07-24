#!/usr/bin/env sh
# Container entrypoint: bring the schema up to date, then serve.
#
# Migrations run here rather than in the app's on_startup so that a failed
# migration stops the container outright instead of leaving a running API
# serving against a half-known schema.
set -e

echo "[entrypoint] running migrations..."
alembic -c /app/backend/alembic.ini upgrade head

echo "[entrypoint] starting api..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
