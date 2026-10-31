# Peck Deck

## What is this project

Peck Deck is a smart bird feeder. A Raspberry Pi 5 with a camera detects bird
visits, captures images, classifies the species through one of three ML tiers,
and notifies users. A React web app and a Python backend on a home gaming PC are
the management hub.

`README.md` says what is built and what comes next. `PRD.md` has the
requirements. Old plans and agent config live in `docs/archive/`. Treat them as
history, not instructions.

## Read these when the work touches them

| Topic | File |
|---|---|
| Live updates over SSE | `docs/live-updates-sse.md` |
| PWA and web push | `docs/pwa-and-web-push.md` |
| Live video and the WHEP relay | `docs/live-video.md` |
| Backups, migrations, health, OpenAPI, test suites | `docs/operations.md` |
| Running anything locally | `CONTRIBUTING.md` |
| Pi setup | `SETUP.md` |
| Model provenance and measured accuracy | `machine_learning/MODELS.md` |

Everything below is what an agent gets wrong without being told. If a fact is
derivable by reading the code or running `ls`, it does not belong here.

## Stack

- The backend is **Litestar, not FastAPI**. The inference server is FastAPI. They
  are separate services. Do not mix them up.
- PostgreSQL, async through asyncpg and SQLAlchemy 2.0.
- **Images live in the database as `bytea`**, not on disk. The `image_data` column
  on Sightings, served by `GET /sightings/{id}/image` with auth required.
- `docker compose up` runs `api` and `db`. **The inference server runs bare metal**,
  because it needs direct GPU access.
- Model weights are fetched, not committed. `python scripts/fetch_models.py`.

## Code conventions

- Async everywhere for database and network I/O.
- Bcrypt before any password reaches the database.
- `raspberry_pi_code/` must run without the backend. It calls the API over HTTP.
- The Pi uploads a sighting as **one multipart POST**, image bytes and metadata
  together.
- `BackendClient.post_sighting` returns an `UploadOutcome`, not a bool. "Network
  down" retries and "token refused" re-provisions, so they cannot share a return
  value. Only `OK` is truthy, so `if ok:` still reads correctly.
- **The offline queue outranks the image cache.** A queued sighting's image is
  never evicted, and neither is a capture waiting for or under classification.
  `MAX_CACHE_IMAGES` bounds unqueued images only. `MAX_QUEUED_SIGHTINGS` bounds
  the backlog.
- **The Pi camera has one owner.** `main.py` opens one `PiCamera` and passes it to
  both the trigger and the pipeline. picamera2 refuses a second open while the
  camera trigger streams, so new Pi code takes that instance and never opens its
  own. `PiCamera` serialises every request behind one lock.
- The camera trigger's visit gap is the only repeat rule. The pipeline has none,
  so it captures every trigger it receives.
- Notifications are fire and forget. `asyncio.create_task()` in the sighting
  controller, and the notification service opens its own DB session.
- **A push subscription row is the push opt-in.** There is no `notify_push` column
  to keep in sync. Deleting the row turns push off.
- Secrets go in `.env` files. Never commit them.
- **Alembic owns the schema. Never call `create_all()` in app code.** Change a
  model, generate a migration. The container migrates on start.
- After changing a route, run `python scripts/export_openapi.py`, so the contract
  change shows up as a diff in review.

## Classification tiers

The Pi decides bird or no bird with the camera, and every bird capture goes to
Tier 2 on the gaming PC. Tier 3 stays in the code, off by default.

Tier 1 runs TFLite on the Pi. Tier 2 is the LAN GPU server at `POST /classify`.
Tier 3 relays through the backend to the Claude API. `TIER_PREFERENCE` sets the
order, and a tier that fails or falls below its threshold hands over to the next.
The default `gpu` runs Tier 2, then Tier 1, and never calls Claude. Only `auto`
(1, 2, 3) and `cloud` (3, 2, 1) reach Tier 3. An unknown value refuses to start,
because it used to fall through to `auto` and turn on paid calls. The full table
is in `SETUP.md` §7.

**A capture is never discarded for want of a species.** If every tier fails, the
Pi uploads or queues it as "Unknown" with tier `none`. The camera already
decided it was a bird.

**Thresholds are per tier, and measured.** `DEFAULT_TIER_THRESHOLDS` in
`raspberry_pi_code/config.py` holds local 0.85, gpu 0.60, cloud 0.50. A single 0.5
across all three accepted the wrong species 18.2% of the time on Tier 1, silently,
because a confidently wrong tier never escalates. They differ per tier for two
reasons. The numbers are not comparable, since Tier 2 softmaxes over 10,000
classes against Tier 1's 965. And the escalations cost differently, since Tier 1
escalates to a free LAN GPU while Tier 2 escalates to a paid Claude call. Override
with `TIER1_/TIER2_/TIER3_CONFIDENCE_THRESHOLD`.

**Tiers 1 and 2 share one label space**, `machine_learning/taxonomy.csv`. Tier 1
indexes into it directly. Tier 2 projects its own 10,000 classes onto it by
scientific name, and 869 of them map. That is what makes the two answers
comparable. Row order **is** the index contract. Regenerate the file, never
hand-edit it.

Accuracy claims belong in `machine_learning/MODELS.md` under *Measured accuracy*.
Measure one tier with `scripts/validate_tiers.py` and the whole chain with
`scripts/simulate_tier_chain.py`. A misaligned taxonomy scores near zero there.

## Security

- `POST /users` is owner only. It was once unauthenticated with a client-settable
  `role`, so anyone could mint an owner account.
- `POST /login` throttles per account and per client IP. Five failures in five
  minutes returns 429 with `Retry-After`.
- Unknown email and wrong password return the same response, so accounts cannot be
  enumerated.
- CORS takes an explicit allowlist in `CORS_ALLOW_ORIGINS`. `*` is rejected,
  because credentials are allowed.
- `MAX_UPLOAD_BYTES` caps bodies at 15 MB by default, since images buffer into
  `bytea`.
- With `ENVIRONMENT=production` the app refuses to start on a default or short
  `JWT_SECRET`, or on wildcard CORS.
- Device tokens and user JWTs have separate guards. A device token is not accepted
  on a user route.
- CI runs `pip-audit` and `npm audit` without failing the build. Read the audit job
  output rather than trusting a green tick.

## Traps in the subsystems

Full detail is in the linked docs. These are the ones that cause silent damage.

- **`publish()` in `backend/events/hub.py` is sync, non-blocking, and never
  raises.** It runs on the Pi's upload path, so a browser that stopped reading must
  not be able to slow or fail an upload.
- **The SSE stream must not take the `db` dependency.** `provide_db` holds a
  session and a transaction for the whole request, and an SSE request lives for
  hours. It would pin a pooled connection and leave Postgres idle-in-transaction
  per open tab.
- The SSE client is not `EventSource`. `EventSource` cannot send an
  `Authorization` header, and every route here is Bearer JWT.
- In-process fan-out assumes a single API process. With two, a browser on process A
  never sees a sighting written by process B, silently.
- **The VAPID public key is derived from the private key**, never read from
  `VAPID_PUBLIC_KEY`. A mismatched pair fails only at delivery time, on every send.
  Never rotate the keypair, because browsers bake the public key into their
  subscriptions.
- The service worker only registers in a production build, so `npm run build`
  comes before any PWA or push testing.

## Health endpoints

`GET /health` checks nothing, deliberately, so a database blip never restarts a
healthy container. `GET /ready` checks the database and the migration revision, and
the compose healthcheck targets it. Detail in `docs/operations.md`.
