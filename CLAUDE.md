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
│   ├── MODELS.md              # Model provenance, measured accuracy, conventions
│   ├── taxonomy.csv           # 965 rows — the Tier 1 model's OWN label space
│   ├── feeder_species.csv     # 20 curated backyard birds (simulator/demo)
│   └── yolo_test.ipynb        # YOLOv5n proof-of-concept notebook
│   #  weights are fetched, not committed: python scripts/fetch_models.py
├── backend/                   # Python REST API (Litestar)
│   ├── notifications/         # Email (SendGrid) + SMS (Twilio) + web push + Wikipedia
│   ├── simulator.py           # Virtual feeder — drives the real Pi client (Phase 5)
│   └── demo.py                # DEMO_MODE: boot seed + read-only enforcement
├── inference_server/          # GPU inference server (RTX 5080, gaming PC)
├── frontend/                  # React web app (M5, built) — installable PWA
│   └── public/                # Web manifest, service worker, app icons (Phase 7)
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
| Notifications | SendGrid (email), Twilio (SMS), web push (VAPID) — fire-and-forget |
| Web app install | PWA: web manifest + hand-written service worker (no build plugin) |
| Cloud classification | Claude API (Anthropic) multimodal — M6 |
| Auth | JWT (users) + device token (Pi devices) |

**Important:** The backend uses **Litestar**, not FastAPI. The inference server uses FastAPI (separate service). Don't mix them up.

## Classification Tiers (priority order)
1. **Tier 1 — Local TFLite** — runs on Pi, no network needed. Google AIY
   `birds_V1` (MobileNetV2/iNaturalist), 964 species + `background`.
   Measured: **64.3%** top-1 on field photos (20/20 on clean ones), 57.9 ms on a Pi 5.
2. **Tier 2 — LAN GPU server** — Pi sends image to `inference_server/` at `POST /classify`.
   ViT-L/14 fine-tuned on iNat21 (10,000 classes), projected onto the shared
   taxonomy. Measured: **85.0%** top-1 on field photos (20/20 on clean ones),
   29.1 ms on the RTX 5080.
3. **Tier 3 — Claude API** — Pi sends image to `backend POST /classify`; backend relays to Claude API (M6)

The Pi falls back from Tier 1 → 2 → 3 based on availability and confidence thresholds.

**Escalation thresholds are per tier, and measured** — `DEFAULT_TIER_THRESHOLDS`
in `raspberry_pi_code/config.py`: **local 0.85, gpu 0.60, cloud 0.50**. A single
0.5 for all three accepted the wrong species 18.2% of the time on Tier 1, silently,
because a confidently wrong tier never escalates. Per tier because the numbers
aren't comparable (Tier 2 softmaxes over 10,000 classes to Tier 1's 965) and the
escalations don't cost the same (Tier 1 → a free LAN GPU; Tier 2 → a paid Claude
call). Override with `TIER1_/TIER2_/TIER3_CONFIDENCE_THRESHOLD`; the legacy global
`CONFIDENCE_THRESHOLD` still wins where set, and logs a warning saying so.

Accuracy claims belong in `machine_learning/MODELS.md` → *Measured accuracy*.
Measure with `scripts/validate_tiers.py` (per tier) and
`scripts/simulate_tier_chain.py` (the whole chain, for a threshold change) —
**not** `validate_tier1.py`, which is a 20-image wiring check on clean photos and
will report 100% for both tiers forever.

**Tiers 1 and 2 share one label space** — `machine_learning/taxonomy.csv`. Tier 1
indexes into it directly; Tier 2 projects its own 10,000 classes onto it by
scientific name (869 map). That is what makes their answers comparable. See
`machine_learning/MODELS.md` — especially the warning that `taxonomy.csv` row
order *is* the index contract and must be regenerated, never hand-edited.

## Key Conventions
- **Async everywhere** — all DB and network I/O should be async.
- **Never store plain-text passwords** — always bcrypt before writing to DB.
- **Images in DB as bytea** — `image_data` column on Sightings; served via `GET /sightings/{id}/image` (auth required).
- **Pi code is self-contained** — `raspberry_pi_code/` must run independently of the backend (it calls the API over HTTP).
- **Pi sighting upload is a single multipart POST** — Pi sends image bytes + metadata together to `POST /sightings`.
- **Upload failures are typed, not boolean** — `BackendClient.post_sighting`
  returns an `UploadOutcome`, because "network down" (retry) and "token
  refused" (re-provision) need opposite handling. Only `OK` is truthy, so
  `if ok:` still reads correctly.
- **The offline queue outranks the image cache** — a queued sighting's image is
  never evicted, nor is the capture currently being classified. `MAX_CACHE_IMAGES`
  bounds only *unqueued* images; `MAX_QUEUED_SIGHTINGS` bounds the backlog.
- **Notifications are fire-and-forget** — `asyncio.create_task()` in the sighting controller; notification service opens its own DB session.
- **A push subscription row *is* the push opt-in** — there is no `notify_push`
  column to keep in sync with it. Deleting the row is how push is turned off.
- **Secrets in env vars** — API keys (Claude, SendGrid, Twilio) go in `.env` files, never committed.
- **Schema is owned by Alembic** — never `create_all()` in app code. Change a
  model → generate a migration. The container applies migrations on start.
- **Run via Docker** — `docker compose up` from project root starts both `api` and `db` containers.
- **Inference server runs bare-metal** — it needs direct GPU access; no Docker for the inference server.

## Live Updates (SSE)
The web app used to load its dataset once on mount and never refetch, so a
running feeder changed nothing on screen until someone reloaded the page.
`GET /events` is a Server-Sent Events stream of new sightings; `DataContext`
holds it open for the life of the session.

| Piece | Where | Notes |
|---|---|---|
| Fan-out | `backend/events/hub.py` | In-process asyncio pub/sub. `publish()` is **sync, non-blocking and never raises** — it runs on the Pi's upload path, so a browser that stopped reading must not be able to slow or fail an upload. |
| Publish seam | `backend/sightings/aftercare.py` | The one "a sighting happened" hook, shared by `POST /sightings` and `POST /dev/sighting`. |
| Stream | `backend/events/controller.py` | Scoping, `Last-Event-ID` replay, heartbeats. |
| Client | `frontend/src/events.js` | `fetch` + `ReadableStream`, not `EventSource`. |

Notes that will bite otherwise:
- **The event carries the sighting row**, so the feed costs no refetch. Only the
  derived aggregates are re-read (`fetchAggregates` — species-counts, heatmap,
  dashboard, devices: ~9 KB against the ~37 KB of a full `fetchRaw`). They are
  refetched rather than recomputed in the browser, because recomputing would be
  a second implementation of the backend's aggregation, free to drift.
- **Not `EventSource`.** It cannot send an `Authorization` header and every
  route here is Bearer-JWT. A token in the query string would land in access
  logs; cookie auth would mean rebuilding the auth model for one endpoint. So
  the client parses SSE framing itself and keeps the header.
- **The stream must not take the `db` dependency.** `provide_db` opens a session
  *and* a transaction for the life of the request, and an SSE request lives for
  hours — it would pin a pooled connection and leave Postgres idle-in-transaction
  per open tab. It opens short sessions for connect-time work and none after.
- **A streamed sighting is inserted by timestamp, not prepended** — the Pi's
  offline queue uploads backdated captures, so the highest id can be the oldest
  visit.
- **In-process fan-out is a single-process assumption.** With two API processes
  a browser on process A never sees a sighting written by process B, silently.
  The fix is Postgres `LISTEN/NOTIFY` behind the same `publish`/`subscribe`
  pair — asyncpg has `add_listener`, and the database is already what both
  processes share.
- A subscriber's device scope is resolved **once, at connect**, so a device
  shared with a user mid-stream appears on their next reconnect.

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
`machine_learning/feeder_species.csv` — a curated subset of the model's full
label space, so every simulated bird is both plausible at a feeder and one Tier 1 could
actually predict); visits are dawn/dusk weighted; confidence is drawn from a
per-tier band. Placeholder capture images are drawn at run time from each
species' palette — **needs Pillow**, which is in `backend/requirements-dev.txt`
(the API container never imports it).

**Dev tools** (`DEV_TOOLS=1`) put a **Simulate a visit** button on the dashboard
(`POST /dev/sighting`): one fabricated visit from a random catalogued species, on
a random station the caller can see.

It is not a second upload path: it calls `create_sighting` +
`schedule_aftercare`, the same two calls `POST /sightings` makes, so the row,
the aggregates and the notification fan-out are identical to a real visit. What
it skips is the wire (no multipart, no device token) — the Pi contract stays
pinned by the simulator and the contract tests. The route is registered always
but 404s when the flag is off, is kept out of the OpenAPI document, is forced
off when `ENVIRONMENT=production`, and is deliberately *not* on the `DEMO_MODE`
allowlist.

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

## PWA & Web Push (Phase 7)
The web app installs to a phone home screen, opens offline to cached content, and
can deliver a new-sighting alert as a browser notification.

```bash
# The service worker only registers in a production build, so this is how the
# PWA (install prompt, offline reload, push) is exercised locally:
cd frontend && npm run build && npm run preview   # :4173, /api proxied

# Generate a VAPID keypair for push, then put it in .env (see .env.example)
python scripts/generate_vapid_keys.py

# Re-render the app icons after changing the brand mark (needs Pillow)
python scripts/generate_pwa_icons.py
```

| Piece | Where | Notes |
|---|---|---|
| Manifest + icons | `frontend/public/` | Icons are generated from the sidebar's own brand mark and committed. |
| Service worker | `frontend/public/sw.js` | Hand-written: network-first shell, cache-first hashed assets, network-first-with-fallback API reads. Never caches a non-GET or a non-200, so a 401 can't outlive the session. No `skipWaiting` — a new worker takes over on the next visit. |
| Offline reads | `frontend/src/offline.js` | Last raw API payloads in localStorage, re-mapped through `mapAll` on open. Cleared on sign-out. **Reads only** — no write queue. |
| Push transport | `backend/notifications/push_sender.py` | RFC 8291 encryption + RFC 8292 VAPID on `cryptography` + `aiohttp`. Not `pywebpush`, which is synchronous and would need a thread per send. |
| Push routes | `GET /push/config`, `POST`/`DELETE /push/subscriptions` | Config reports `enabled:false` when no keys are set, and the web app hides the opt-in. |

Notes that will bite otherwise:
- **The VAPID public key is derived from the private key**, never read from
  `VAPID_PUBLIC_KEY` (which is only cross-checked). A mismatched pair fails only
  at delivery time, on every send.
- **Keep the keypair stable.** Browsers bake the public key into their
  subscription; rotating it silently invalidates every existing subscription.
- **Push subscription writes are blocked in `DEMO_MODE`** and deliberately not on
  the allowlist — every demo visitor shares one account, so one subscription
  would push every later sighting to all the others' browsers.
- A 404/410 from a push service prunes the subscription; a 429/500 leaves it.

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
| `docs/openapi.json` | Committed snapshot — 28 paths, 37 operations |

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

FLEDGE roadmap Phases 0–3 and 5–8 are complete: CI + docs, backend hardening,
frontend polish, the integration/contract suite (real Postgres + live-server seam
tests), the device simulator + demo mode, analytics/export, the installable PWA
with web push, and production readiness. Remaining work is tracked in
`FLEDGE_ROADMAP.md`. **Phase 4 — physical hardware bring-up** (trigger sensor,
real model weights) is the only phase still open.

## Agent skills
Configuration for the `mattpocock-skills` engineering skills (`/wayfinder`,
`/triage`, `/to-tickets`, `/to-spec`, …). Nothing else reads these files.

### Issue tracker
Issues live in this repo's **GitHub Issues** (`dnorris823/Peck_Deck`), driven by
the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels
The five canonical roles, kept at their default names (`needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) — the repo had no
existing label vocabulary to map onto. See `docs/agents/triage-labels.md`.

### Domain docs
**Single-context**: one `CONTEXT.md` at the root plus `docs/adr/`. Neither exists
yet; `/domain-modeling` creates them lazily. See `docs/agents/domain.md`.
