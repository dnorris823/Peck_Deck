#!/usr/bin/env bash
# Back up the Peck Deck database, including the bytea-stored sighting images.
#
#   scripts/backup.sh                    # -> backups/peck_deck_<UTC timestamp>.dump
#   scripts/backup.sh /path/to/out.dump  # explicit destination
#
# Uses pg_dump's custom format (-Fc): compressed, and the only format
# scripts/restore.sh can feed to pg_restore. Plain SQL would also work but
# balloons on bytea (images are hex-escaped) and cannot be restored selectively.
#
# Runs pg_dump *inside* the db container, so no local postgres client is needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_NAME="${POSTGRES_DB:-peck_deck}"
DB_USER="${POSTGRES_USER:-peck_deck}"
SERVICE="${DB_SERVICE:-db}"

if [ $# -ge 1 ]; then
    DEST="$1"
else
    mkdir -p backups
    DEST="backups/peck_deck_$(date -u +%Y%m%dT%H%M%SZ).dump"
fi

echo "[backup] dumping '$DB_NAME' from container service '$SERVICE'..."

# -Fc custom format, on stdout so it lands on the host rather than in the
# container's ephemeral filesystem.
docker compose exec -T "$SERVICE" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner --no-privileges > "$DEST"

SIZE=$(wc -c < "$DEST")
if [ "$SIZE" -lt 1024 ]; then
    echo "[backup] FAILED: dump is only ${SIZE} bytes — refusing to keep it" >&2
    rm -f "$DEST"
    exit 1
fi

echo "[backup] wrote $DEST ($(echo "$SIZE" | awk '{printf "%.1f MB", $1/1048576}'))"
