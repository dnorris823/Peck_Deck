#!/usr/bin/env bash
# Restore a Peck Deck backup produced by scripts/backup.sh.
#
#   scripts/restore.sh backups/peck_deck_20260724T210000Z.dump
#   scripts/restore.sh <dump> peck_deck_scratch     # restore into another database
#
# DESTRUCTIVE against the target database: every existing object is dropped and
# replaced. Restoring over the default database requires typing the database
# name to confirm; restoring into a non-default one does not.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DUMP="${1:-}"
DEFAULT_DB="${POSTGRES_DB:-peck_deck}"
TARGET_DB="${2:-$DEFAULT_DB}"
DB_USER="${POSTGRES_USER:-peck_deck}"
SERVICE="${DB_SERVICE:-db}"

if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "usage: scripts/restore.sh <dump-file> [target-database]" >&2
    exit 1
fi

if [ "$TARGET_DB" = "$DEFAULT_DB" ] && [ -z "${PECK_RESTORE_YES:-}" ]; then
    echo "About to DROP and rebuild every object in '$TARGET_DB'."
    printf "Type the database name to confirm: "
    read -r reply
    if [ "$reply" != "$TARGET_DB" ]; then
        echo "[restore] aborted" >&2
        exit 1
    fi
fi

echo "[restore] restoring $DUMP into '$TARGET_DB'..."

# Ensure the target exists (no-op if it already does).
docker compose exec -T "$SERVICE" \
    psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=0 \
    -c "CREATE DATABASE \"$TARGET_DB\" OWNER \"$DB_USER\";" >/dev/null 2>&1 || true

# --clean --if-exists drops existing objects first, so this is idempotent.
# pg_restore exits non-zero on benign notices (e.g. "does not exist" during
# --clean on a fresh database), so failures are judged by verification below.
docker compose exec -T "$SERVICE" \
    pg_restore -U "$DB_USER" -d "$TARGET_DB" --clean --if-exists --no-owner --no-privileges \
    < "$DUMP" || echo "[restore] pg_restore reported warnings (often benign) — verifying..."

echo "[restore] verifying..."
docker compose exec -T "$SERVICE" psql -U "$DB_USER" -d "$TARGET_DB" -At -c "
SELECT 'sightings=' || count(*) ||
       ' with_images=' || count(image_data) ||
       ' image_bytes=' || coalesce(sum(octet_length(image_data)), 0)
FROM sightings;"

echo "[restore] done. Restart the api so it reconnects: docker compose restart api"
