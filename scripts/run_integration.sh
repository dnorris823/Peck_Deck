#!/usr/bin/env bash
#
# Phase 3 — one command to spin the stack and run the integration + contract
# suite green end-to-end, with no physical Pi or GPU.
#
#   scripts/run_integration.sh              # bring up postgres via compose, run, tear down
#   scripts/run_integration.sh -k contract  # extra args are passed through to pytest
#
# If PECK_TEST_DATABASE_URL is already exported (e.g. you have a Postgres you
# want to reuse, or CI provides a service container) the script uses it as-is
# and skips docker entirely.
set -euo pipefail
cd "$(dirname "$0")/.."

export JWT_SECRET="${JWT_SECRET:-local-integration-secret-key-at-least-32-bytes!!}"

# ── Reuse an externally provided database ────────────────────────────────────
if [[ -n "${PECK_TEST_DATABASE_URL:-}" ]]; then
  echo "==> Using existing PECK_TEST_DATABASE_URL"
  exec python -m pytest integration_tests/ -q "$@"
fi

# ── Otherwise, stand up postgres:16 via docker compose ───────────────────────
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-changeme}"
COMPOSE="docker compose -f docker-compose.test.yml"

cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Starting postgres:16 ..."
$COMPOSE up -d

echo "==> Waiting for postgres to become healthy ..."
for _ in $(seq 1 30); do
  if $COMPOSE exec -T db pg_isready -U peck_deck -d peck_deck >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
$COMPOSE exec -T db pg_isready -U peck_deck -d peck_deck >/dev/null 2>&1 \
  || { echo "postgres did not become ready in time" >&2; exit 1; }

export PECK_TEST_DATABASE_URL="postgresql+asyncpg://peck_deck:${POSTGRES_PASSWORD}@localhost:5432/peck_deck"

echo "==> Running integration + contract tests ..."
python -m pytest integration_tests/ -q "$@"
