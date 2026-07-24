#!/usr/bin/env bash
# Prove a backup can actually be restored — including the bytea image payloads.
#
#   bash scripts/backup_smoke_test.sh
#
# Dumps the live database, restores it into a throwaway database, and compares
# row counts and a SHA-256 of the concatenated image bytes on both sides. The
# live database is only ever read; the scratch database is dropped at the end.
#
# The image digest is the point of this test: a backup that restores the rows
# but silently truncates or re-encodes bytea would lose every sighting photo,
# and a plain row count would never notice.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_NAME="${POSTGRES_DB:-peck_deck}"
DB_USER="${POSTGRES_USER:-peck_deck}"
SERVICE="${DB_SERVICE:-db}"
SCRATCH="peck_deck_restore_test"
DUMP="$(mktemp -t peckdeck_smoke_XXXXXX.dump)"

cleanup() {
    rm -f "$DUMP"
    docker compose exec -T "$SERVICE" \
        psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Fingerprint = row counts + digest of all image bytes, ordered deterministically.
fingerprint() {
    docker compose exec -T "$SERVICE" psql -U "$DB_USER" -d "$1" -At -c "
    SELECT (SELECT count(*) FROM sightings) || '|' ||
           (SELECT count(*) FROM species)   || '|' ||
           (SELECT count(*) FROM users)     || '|' ||
           (SELECT count(*) FROM devices)   || '|' ||
           coalesce((SELECT encode(sha256(string_agg(image_data, ''::bytea ORDER BY id)), 'hex')
                     FROM sightings WHERE image_data IS NOT NULL), 'no-images');"
}

echo "== 1. fingerprint live database =="
BEFORE=$(fingerprint "$DB_NAME")
echo "   $BEFORE"

echo "== 2. dump =="
bash scripts/backup.sh "$DUMP"

echo "== 3. restore into scratch database '$SCRATCH' =="
docker compose exec -T "$SERVICE" \
    psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\";" >/dev/null
PECK_RESTORE_YES=1 bash scripts/restore.sh "$DUMP" "$SCRATCH" >/dev/null

echo "== 4. fingerprint restored database =="
AFTER=$(fingerprint "$SCRATCH")
echo "   $AFTER"

echo
if [ "$BEFORE" = "$AFTER" ]; then
    echo "PASS — restored database matches the original, image bytes included."
    exit 0
fi

echo "FAIL — restored database differs from the original:" >&2
echo "  before: $BEFORE" >&2
echo "  after:  $AFTER" >&2
exit 1
