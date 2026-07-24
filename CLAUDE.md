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
│   └── notifications/         # Email (SendGrid) + SMS (Twilio) + Wikipedia lookup
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
  `backend/fixtures.py` (`seed_reference_data`).

## Build Status (as of July 2026)
Milestones M1–M6 are merged to `main`:
- **M5 — React frontend** — built (dashboard, gallery, species library, devices, settings).
- **M6 — Claude API Tier 3** — built; `POST /classify` relays to the Claude multimodal API.
- Wikipedia URL lookup (PRD §9.1) — built.

FLEDGE roadmap Phases 0–3 are complete: CI + docs, backend hardening, frontend
polish, and the integration/contract suite (real Postgres + live-server seam
tests). Remaining work is tracked in `FLEDGE_ROADMAP.md`. **Phase 4 — physical
hardware bring-up** (Pi camera/trigger, GPU inference server on the RTX 5080) is
still open.
