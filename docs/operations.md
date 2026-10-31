# Operations

Moved out of `CLAUDE.md`. Backups, migrations, health endpoints and the OpenAPI
snapshot. The rules an agent breaks by default stay in `CLAUDE.md`; the commands
and the reasoning live here.

## Backup and restore

Sighting images live in the database as `bytea`, so the database dump *is* the
media backup — there is no separate image directory to copy.

```bash
bash scripts/backup.sh                      # -> backups/peck_deck_<UTC>.dump
bash scripts/restore.sh <dump>              # DESTRUCTIVE; prompts for confirmation
bash scripts/restore.sh <dump> scratch_db   # restore elsewhere (no prompt)
bash scripts/backup_smoke_test.sh           # prove a dump actually restores
```

- Uses `pg_dump -Fc` (custom format): compressed, and required by `pg_restore`.
  Plain SQL balloons on `bytea` because images get hex-escaped.
- Runs inside the `db` container, so no local postgres client is needed.
- `backup_smoke_test.sh` restores into a throwaway database and compares row
  counts **and a SHA-256 of the concatenated image bytes**. That digest is the
  point: a backup that restored rows but truncated `bytea` would lose every
  photo, and a row count alone would never catch it.
- `backups/` and `*.dump` are gitignored — they hold real user records and photos.

## Database size and retention

Images have no size limit, so the database and the backup dump grow with every
capture. Settings > Storage shows two numbers from `GET /stats/storage`:

| Number | Source |
|---|---|
| Database | `pg_database_size(current_database())`, the whole database on disk |
| Images | `sum(octet_length(image_data))` plus the same for `thumbnail_data` |

Both cover every device on the server. The image number is part of the database
number.

### The retention rule

One optional rule exists: delete "Unknown" sightings older than N days. An
Unknown sighting is one that no tier could name, so the Pi uploaded it under the
"Unknown" species with tier `none`. A sighting a person corrected to a real
species no longer points at "Unknown", so the rule skips it.

| Env var | Default | Effect |
|---|---|---|
| `RETENTION_UNKNOWN_DAYS` | `0` | `0` turns the rule off. A positive N deletes Unknown sightings older than N days. A negative value refuses to start. |

- **The rule is off by default.** With `0`, the API starts no task and deletes
  nothing.
- When on, the API process runs the rule once at startup and then every 24 hours.
  The code is in `backend/retention.py`.
- Each run logs one line with the count, such as
  `retention: deleted 12 Unknown sightings older than 30 days`.
- A deleted row takes its image with it, because the image is a column on the
  row. Nothing restores it except a backup taken before the run.
- Postgres does not shrink the file at once. Autovacuum reuses the freed space
  for new rows, so the database number stops growing before it falls.

Set it in the root `.env`, which compose passes to the `api` container, then
restart the container:

```bash
RETENTION_UNKNOWN_DAYS=30
```

## Database migrations

Schema is versioned with Alembic (`backend/migrations/`). The API container runs
`alembic upgrade head` before uvicorn starts, so `docker compose up` is always
migrated. For manual runs:

```bash
bash scripts/migrate.sh                 # upgrade to head
bash scripts/migrate.sh current         # what revision is this DB on?
bash scripts/migrate.sh check           # fail if models drifted from migrations
bash scripts/migrate.sh revision --autogenerate -m "add foo"
```

- **After changing a model, generate a migration** — `integration_tests/test_migrations.py`
  fails CI if the two drift apart.
- The test suites still build their schema with `create_all()` for speed; that
  drift test is what keeps it honest.
- **Upgrading an existing database that predates Alembic:** stamp it rather than
  upgrading, so the baseline isn't replayed over live tables —
  `bash scripts/migrate.sh stamp head`.

## Health and readiness

| Endpoint | Purpose | Checks |
|---|---|---|
| `GET /health` | Liveness — is the process up? | Nothing. Deliberately dependency-free, so a DB blip never restarts a healthy container. |
| `GET /ready` | Readiness — can it serve? | DB reachable **and** schema migrated to a revision this build knows. 503 when not. |

The compose healthcheck targets `/ready`, so `docker compose ps` only reports
`healthy` once the container can actually serve. Use `/health` for liveness
probes and `/ready` for load-balancer membership.

## API documentation

The OpenAPI schema is generated from the route handlers and served by the
running app:

| URL | What |
|---|---|
| `http://localhost:8000/schema` | Interactive docs (Swagger UI / ReDoc) |
| `http://localhost:8000/schema/openapi.json` | Raw OpenAPI 3.1 document |
| `docs/openapi.json` | Committed snapshot — 33 paths, 44 operations |

Both auth schemes are documented in the spec (`UserJWT`, `DeviceToken`), so the
Pi/frontend contract is self-describing.

**After changing a route, regenerate the snapshot** so the contract change shows
up as a diff in review:

```bash
python scripts/export_openapi.py
```

## Test suites

- **Unit tests** (`backend/tests/`) run against SQLite (`aiosqlite`) for speed.
- **Integration + contract tests** (`integration_tests/`) run against real
  PostgreSQL and drive the real Pi `aiohttp` clients against live uvicorn
  servers (GPU mocked). They are gated on `PECK_TEST_DATABASE_URL`, so the
  default `pytest -q` never touches them.
- The deterministic test dataset is shared by both suites via
  `backend/fixtures.py` (`seed_reference_data`). The larger, randomized dataset
  for local web-app work lives separately in `backend/seed.py`
  (`python -m backend.seed`).

Commands for running them are in `CONTRIBUTING.md`.

## Dependency audits

`pip-audit` and `npm audit` run in CI on every push. They report without failing
the build, because a transitive CVE with no fix should not block unrelated work.
So **read the audit job output** rather than trusting a green tick.
