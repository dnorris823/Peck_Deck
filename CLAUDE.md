# Peck Deck — Claude Code Instructions

## What Is This Project
Peck Deck is a smart bird feeder system. A Raspberry Pi 5 with camera and trigger peripheral detects bird visits, captures images/video, classifies the species via one of three ML tiers, and notifies registered users. A React web app + Python backend running on a home gaming PC serves as the management hub.

See `PRD.md` for full product requirements.

## Repository Layout
```
Peck_Deck/
├── PRD.md                     # Product requirements — source of truth for scope
├── CLAUDE.md                  # This file
├── raspberry_pi_code/         # Pi-side capture + classification pipeline
├── machine_learning/          # Models, notebooks, taxonomy data
│   ├── INatVision_Small_2_fact256_8bit.tflite   # Tier 1 on-device model
│   ├── taxonomy.csv           # Maps model output indices → species names
│   └── yolo_test.ipynb        # YOLOv5n proof-of-concept notebook
├── backend/                   # Python REST API (Litestar)
│   ├── notifications/         # Email (SendGrid) + SMS (Twilio) + Wikipedia lookup
│   ├── simulator.py           # Virtual feeder — drives the real Pi client (Phase 5)
│   └── demo.py                # DEMO_MODE: boot seed + read-only enforcement
├── inference_server/          # GPU inference server (RTX 5080, gaming PC)
├── frontend/                  # React web app (M5, built)
└── requirements.txt
```

## Tech Stack
| Layer | Technology |
|---|---|
| Pi runtime | Python 3.11+, asyncio |
| Pi classification (Tier 1) | TFLite runtime + INatVision model |
| Backend API | Python — **Litestar** framework (not FastAPI) |
| Database | **PostgreSQL** (async via asyncpg + SQLAlchemy 2.0) |
| Media storage | Images stored as **bytea** in PostgreSQL (not on disk) |
| Deployment | **Docker + docker-compose** (two containers: `api` + `db`) |
| GPU inference server | Python + **FastAPI** + PyTorch/timm, RTX 5080 |
| Notifications | SendGrid (email), Twilio (SMS) — fire-and-forget |
| Cloud classification | Claude API (Anthropic) multimodal — M6 |
| Auth | JWT (users) + device token (Pi devices) |

**Important:** The backend uses **Litestar**, not FastAPI. The inference server uses FastAPI (separate service). Don't mix them up.

## Classification Tiers (priority order)
1. **Tier 1 — Local TFLite** — runs on Pi, no network needed
2. **Tier 2 — LAN GPU server** — Pi sends image to `inference_server/` at `POST /classify`
3. **Tier 3 — Claude API** — Pi sends image to `backend POST /classify`; backend relays to Claude API (M6)

The Pi falls back from Tier 1 → 2 → 3 based on availability and confidence thresholds.

## Key Conventions
- **Async everywhere** — all DB and network I/O should be async.
- **Never store plain-text passwords** — always bcrypt before writing to DB.
- **Images in DB as bytea** — `image_data` column on Sightings; served via `GET /sightings/{id}/image` (auth required).
- **Pi code is self-contained** — `raspberry_pi_code/` must run independently of the backend (it calls the API over HTTP).
- **Pi sighting upload is a single multipart POST** — Pi sends image bytes + metadata together to `POST /sightings`.
- **Notifications are fire-and-forget** — `asyncio.create_task()` in the sighting controller; notification service opens its own DB session.
- **Secrets in env vars** — API keys (Claude, SendGrid, Twilio) go in `.env` files, never committed.
- **Schema is owned by Alembic** — never `create_all()` in app code. Change a
  model → generate a migration. The container applies migrations on start.
- **Run via Docker** — `docker compose up` from project root starts both `api` and `db` containers.
- **Inference server runs bare-metal** — it needs direct GPU access; no Docker for the inference server.

## Device Simulator & Demo Mode
There is no Pi needed to see the app work. `backend/simulator.py` is a virtual
feeder that drives the **real Pi client** (`raspberry_pi_code.api_client.
BackendClient`) against `POST /sightings`, so it exercises the exact multipart
contract the hardware uses — there is no second upload implementation to drift.

```bash
# Backfill history: 120 sightings over the last 14 days, then exit
python -m backend.simulator --mode burst --count 120 --days 14

# Live drip: one sighting every ~8s until Ctrl-C (watch the dashboard update)
python -m backend.simulator --mode live --interval 8
```

With no `--device-token` it signs in as the demo owner and reads tokens straight
off `GET /devices`, so a seeded stack needs zero configuration. Species come from
`machine_learning/taxonomy.csv` (so every simulated bird is one Tier 1 could
actually predict); visits are dawn/dusk weighted; confidence is drawn from a
per-tier band. Placeholder capture images are drawn at run time from each
species' palette — **needs Pillow**, which is in `backend/requirements-dev.txt`
(the API container never imports it).

**Demo mode** (`DEMO_MODE=1`) makes an instance safe to hand out:

| Behaviour | Detail |
|---|---|
| Boot seed | Seeds the demo dataset if the DB is empty. Never seeds twice; a failure logs and boots anyway. Schema still belongs to Alembic. |
| Read-only | Every user-authenticated write returns 403 with the standard error envelope. |
| Still live | `POST /sightings`, `POST /classify`, the device heartbeat and `POST /login` keep working — that's what lets the simulator keep the feed moving. |
| Discovery | `GET /meta` reports `demo_mode` and (only in demo mode) the demo login, so the frontend shows a banner and a one-click sign-in. |

The allowlist in `backend/demo.py` is the whole security surface — the check runs
as ASGI middleware, *before* any guard, so it decides on method + path alone.
Adding a device-facing route means adding it there too.

## Running Locally
```powershell
# Start backend + database (from project root)
docker compose up --build

# Start the GPU inference server (run from the PROJECT ROOT, not inference_server/)
# Install deps first: pip install -r inference_server/requirements.txt
# The RTX 5080 is Blackwell (sm_120) — it needs the cu128 wheels. The cu124
# build has no sm_120 kernels and will fail on this card:
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m inference_server

# Start the React frontend (from frontend/)
npm run dev
```

## API Documentation
The OpenAPI schema is generated from the route handlers and served by the
running app:

| URL | What |
|---|---|
| `http://localhost:8000/schema` | Interactive docs (Swagger UI / ReDoc) |
| `http://localhost:8000/schema/openapi.json` | Raw OpenAPI 3.1 document |
| `docs/openapi.json` | Committed snapshot — 25 paths, 32 operations |

Both auth schemes are documented in the spec (`UserJWT`, `DeviceToken`), so the
Pi/frontend contract is self-describing.

**After changing a route, regenerate the snapshot** so the contract change shows
up as a diff in review:
```bash
python scripts/export_openapi.py
```

## Security Model
| Control | Behaviour |
|---|---|
| `POST /users` (invite) | **Owner only.** Was unauthenticated with a client-settable `role` — anyone could mint an owner account. |
| `POST /login` | Throttled per account **and** per client IP: 5 failures / 5 min, then 429 + `Retry-After`. |
| Auth failures | Identical response for unknown-email and wrong-password, so accounts can't be enumerated. |
| CORS | Explicit origin allowlist (`CORS_ALLOW_ORIGINS`); `*` is rejected because credentials are allowed. |
| Upload size | Bodies capped at `MAX_UPLOAD_BYTES` (15 MB default) — images are buffered into `bytea`. |
| Production boot | With `ENVIRONMENT=production` the app refuses to start on a default/short `JWT_SECRET` or wildcard CORS. |
| Device vs user tokens | Separate guards; a device token is not accepted on user routes. |

Dependency audits (`pip-audit`, `npm audit`) run in CI on every push. They report
without failing the build — a transitive CVE with no fix shouldn't block
unrelated work — so **read the audit job output** rather than trusting a green tick.

## Backup & Restore
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

## Health & Readiness
| Endpoint | Purpose | Checks |
|---|---|---|
| `GET /health` | Liveness — is the process up? | Nothing. Deliberately dependency-free, so a DB blip never restarts a healthy container. |
| `GET /ready` | Readiness — can it serve? | DB reachable **and** schema migrated to a revision this build knows. 503 when not. |
| `GET /meta` | What *is* this instance? | Nothing. Public and unauthenticated: reports `demo_mode` + environment so the web app can render the demo banner before login. |

The compose healthcheck targets `/ready`, so `docker compose ps` only reports
`healthy` once the container can actually serve. Use `/health` for liveness
probes and `/ready` for load-balancer membership.

## Database Migrations
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

## Testing
```powershell
# Backend unit suite — throwaway SQLite, no services needed
pytest -q

# Integration + contract suite — real postgres:16, live in-process servers.
# Spins up Postgres via docker compose, runs, and tears down in one command:
bash scripts/run_integration.sh
```
- **Unit tests** (`backend/tests/`) run against SQLite (`aiosqlite`) for speed.
- **Integration + contract tests** (`integration_tests/`) run against real
  PostgreSQL and drive the real Pi `aiohttp` clients against live uvicorn
  servers (GPU mocked). They are gated on `PECK_TEST_DATABASE_URL`, so the
  default `pytest -q` never touches them.
- The deterministic demo dataset is shared by both suites via
  `backend/fixtures.py` (`seed_reference_data`). The larger, randomized web-app
  dataset lives separately in `backend/seed.py` (`seed_demo_data`), which is
  also what `DEMO_MODE` seeds at boot.
- `integration_tests/test_contract_simulator.py` runs the simulator's real CLI
  against a live server, so the Phase 5 seam is covered by the same mechanism as
  the Pi's.

## Build Status (as of July 2026)
Milestones M1–M6 are merged to `main`:
- **M5 — React frontend** — built (dashboard, gallery, species library, devices, settings).
- **M6 — Claude API Tier 3** — built; `POST /classify` relays to the Claude multimodal API.
- Wikipedia URL lookup (PRD §9.1) — built.

FLEDGE roadmap Phases 0–3, 5, 6 and 8 are complete: CI + docs, backend
hardening, frontend polish, the integration/contract suite (real Postgres +
live-server seam tests), the device simulator + demo mode, analytics/export, and
production readiness. Remaining work is tracked in `FLEDGE_ROADMAP.md`.
**Phase 4 — physical hardware bring-up** (trigger sensor, real model weights)
and **Phase 7 — PWA** are still open.
