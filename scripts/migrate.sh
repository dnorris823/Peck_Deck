#!/usr/bin/env bash
# Run database migrations against the configured DATABASE_URL.
#
#   scripts/migrate.sh              # upgrade to the latest revision
#   scripts/migrate.sh current      # show the revision the DB is on
#   scripts/migrate.sh history      # list all revisions
#   scripts/migrate.sh check        # fail if models have drifted from migrations
#   scripts/migrate.sh downgrade -1 # step back one revision
#   scripts/migrate.sh revision --autogenerate -m "add foo"
#
# DATABASE_URL is read by backend/migrations/env.py from backend.config, so it
# honours .env exactly like the app does. Override inline when needed:
#   DATABASE_URL=postgresql+asyncpg://... scripts/migrate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer the project venv, fall back to whatever alembic is on PATH.
if [ -x ".venv/Scripts/alembic.exe" ]; then
    ALEMBIC=".venv/Scripts/alembic.exe"     # Windows
elif [ -x ".venv/bin/alembic" ]; then
    ALEMBIC=".venv/bin/alembic"             # POSIX
else
    ALEMBIC="alembic"
fi

CONFIG="backend/alembic.ini"

if [ $# -eq 0 ]; then
    exec "$ALEMBIC" -c "$CONFIG" upgrade head
fi

exec "$ALEMBIC" -c "$CONFIG" "$@"
