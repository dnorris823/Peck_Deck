# 🪶 FLEDGE — Peck Deck Development Roadmap

> **Fledge** *(v.)* — when a young bird develops the feathers it needs to fly.
> This roadmap gets the *software* flight-ready while the *hardware* roosts.

A phased plan to finish everything that **doesn't** need the Raspberry Pi or the
RTX 5080 gaming PC in hand — so real progress ships from anywhere, including a
phone — then land the remaining hardware bring-up in one focused pass once you're
back at the bench.

Phases 0–3 are complete. Phase 4 (hardware) is parked until the bench is
available; **Phases 5–8 are all cloud/mobile** and keep the app moving in the
meantime — a live device simulator, deeper analytics, a mobile PWA, and
production hardening.

---

## Legend

| Tag | Meaning |
|---|---|
| ☁️ **Cloud** | Runs fully in the web/cloud dev environment. No Pi, no GPU. Do it from mobile. |
| 🔌 **Hardware-gated** | Needs the physical Pi and/or the RTX 5080. Deferred until you're back. |

**Current state (baseline):** backend (Litestar + Postgres) with 50 passing
tests over SQLite, React/Vite frontend, FastAPI inference server, Tier 3 Claude
classifier and Wikipedia lookup already merged to `main`. No CI yet; docs are
stale.

---

## Phase 0 — 🪺 Nest  ·  Foundation & Guardrails  ☁️

*Lock down the ground the rest of the work stands on. Highest leverage, lowest effort.*

- [x] **Continuous Integration** — `.github/workflows/ci.yml`
  - Backend job: install `backend/requirements-dev.txt`, run `pytest` (SQLite-backed, no Postgres service needed). Matrix: Python 3.11 + 3.12.
  - Frontend job: `npm ci` + `npm run build` in `frontend/`.
  - Trigger on push + PR to `main`.
- [x] **Doc refresh**
  - `CLAUDE.md`: frontend (M5) and Tier 3 (M6) marked **built**; build-status section updated to July 2026.
  - `PRD.md`: stale SQLite references corrected to **PostgreSQL**; the two open questions annotated (resolved at hardware bring-up).
- [x] **Repo hygiene**
  - Added `CONTRIBUTING.md` describing the branch/PR flow and local test commands.
  - Branch protection on `main` documented as a recommended manual repo setting (requires admin in GitHub Settings).

**Exit criteria:** every push runs CI; a new contributor can go from clone → green tests using only the docs. ✅ *(Branch protection is a one-time manual toggle in repo Settings — see CONTRIBUTING.md.)*

---

## Phase 1 — 🧹 Preen  ·  Backend Hardening (M7)  ☁️

*Smooth out the API's rough edges. All independently testable with mocks.*

- [x] Expand test coverage on the untested paths:
  - Auth failures (bad token, expired JWT, wrong role, device-token vs user-JWT).
  - Offline-sync / delayed-sighting flow logic.
  - Wikipedia lookup fallback chain (API → search → scrape → null).
  - Notification min-interval throttle + fire-and-forget failure isolation.
- [x] Consistent error envelopes and input validation across controllers.
  - All failures serialize to `{status_code, type, detail, request_id, extra?}`
    via `backend/errors.py` (`detail` kept for frontend compatibility).
- [x] Structured logging (request IDs, tier-used, notification outcomes).
  - `backend/observability.py`: request-id middleware + a request-id-aware
    root formatter; tier-used logged on sighting create + Tier 3 classify.
- [x] **Tier 3 tuning** — refine the Claude prompt + structured-output schema; add tests that exercise the real Claude API and assert the JSON contract.
  - Schema bounds `confidence` to `[0, 1]`; `normalize_prediction()` is the
    single contract choke point (strips names, clamps/coerces confidence).
  - Contract tests plus an **opt-in** live test (`RUN_LIVE_CLAUDE=1` +
    `ANTHROPIC_API_KEY`), skipped in CI.

**Exit criteria:** coverage meaningfully up from the current 50 tests; error responses are uniform; Tier 3 returns a validated `{common_name, scientific_name, confidence}` every time. ✅ *(50 → 87 passing tests; uniform envelope in place; Tier 3 contract enforced by `normalize_prediction`.)*

---

## Phase 2 — 🎨 Plumage  ·  Frontend Polish (M5 → M7)  ☁️

*Make the web app feel finished. Node-only; runs in the cloud box.*

- [x] Loading / error / empty states across Dashboard, Sightings, Species, Devices.
  - Global loading/error gate already lived in `App.jsx` (boot screen + retry);
    added a shared `Empty` component (`src/Empty.jsx` + `.empty` styles) wired
    into the Sightings gallery (no-results vs. never-any), Species grid, Devices
    grid, and the Dashboard recent-visits feed.
- [x] Form validation (login, user/device settings).
  - `src/validate.js` — email/phone(E.164)/password rules in one testable place;
    inline per-field errors in Login, Invite/Edit user, Change-password, the
    Settings account fields (validate-on-blur), with `aria-invalid` + error text.
    (API-key management is display-only/read-only, so nothing to validate there.)
- [x] **Frontend test setup** — Vitest + React Testing Library + jsdom wired in
  (`frontend/vite.config.js` `test` block, `src/test/setup.js`). 42 tests cover
  `api.js` (token/login/error handling), `data.js` (`loadAll` mapping + formatters
  + device update), `DataContext` (loading/data/error/auth branches), `validate.js`,
  the Sightings range filter, and the `Login` component.
  Runs in CI ahead of the build (`npm test` step in `ci.yml`).
- [x] Accessibility pass (labels, focus, keyboard nav) and responsive/mobile layout.
  - Dialogs get `role="dialog"`/`aria-modal`, Escape-to-close, focus-in-on-open +
    focus-restore-on-close (`useDialog` in `Modal.jsx`); icon-only buttons and the
    search input get `aria-label`s; nav items get `aria-current`; a global
    `:focus-visible` ring. Layout: off-canvas sidebar with a hamburger + backdrop
    on phones, and stacking breakpoints for the stat/dash/settings grids and modals.
- [x] Wire remaining screens to live backend endpoints; confirm the Dusk dark theme end-to-end.
  - Sightings time-range chips now actually filter (`rangeCutoff` + fixed `useMemo`
    deps); DeviceDetail's tier change persists via `PUT /devices/{id}`
    (`updateDevice`) and reloads. Inert placeholders (fake recipient list,
    decommission) replaced with honest read-only states. Dusk theme verified via
    the existing `[data-theme="dusk"]` token remap + Appearance toggle.

**Exit criteria:** no dead/placeholder states; frontend tests run in CI; app is usable on a phone-sized viewport. ✅ *(42 frontend tests — up from zero — green in CI; empty/error/loading states everywhere; off-canvas mobile nav + stacking layout down to 390px.)*

---

## Phase 3 — 🐦 Flock  ·  Integration & E2E  ☁️ *(mostly)*

*Prove the pieces work together — with real Postgres, mocked hardware.*

- [x] Integration tests against the real `postgres:16` service (not just SQLite).
  - `integration_tests/` runs the full Litestar app on PostgreSQL: real bcrypt
    login, device-scoped reads, `bytea` image round-trip, and dashboard/heatmap
    aggregates. Gated on `PECK_TEST_DATABASE_URL` so the default `pytest -q`
    (SQLite) is untouched.
- [x] Contract tests for the seams: Pi client ↔ backend (`POST /sightings`
  multipart), Pi ↔ inference server (`POST /classify`, mocked GPU).
  - The **real** Pi `aiohttp` clients (`api_client.BackendClient`,
    `GPUServerClassifier`) are driven against **live** in-process uvicorn servers
    — nothing mocked on the wire. The GPU classifier is stubbed (no torch/CUDA)
    so the inference contract runs anywhere. Covers happy path, offline-sync
    `delayed=True`, bad device token, and the 503 model-unavailable fallthrough.
- [x] Seed/demo dataset + reusable fixtures for local and CI runs.
  - The deterministic dataset now lives in `backend/fixtures.py`
    (`seed_reference_data`), shared by the SQLite unit conftest and the Postgres
    integration conftest — one source of truth for both.
- [x] Add the integration job to CI (Postgres service container).
  - `ci.yml` `integration` job runs against a `postgres:16` service container;
    `docker-compose.test.yml` + `scripts/run_integration.sh` give the same run
    as a single local command.

**Exit criteria:** a single command spins the stack and runs green end-to-end without any physical device. ✅ *(`scripts/run_integration.sh` brings up Postgres and runs 11 integration + contract tests green; CI runs the same suite on every push/PR.)*

---

## Phase 4 — 🧭 Migration  ·  Hardware Bring-up  🔌

*The one pass that genuinely needs the bench. Everything above de-risks it.*

- [x] **Pi camera capture** — real IMX708 stills via the project's own `PiCamera`
  (~300 KB JPEG at 1920×1080 in ~1.0 s). Trigger/debounce still **blocked**: no
  PIR / IR-beam sensor is wired to the header.
- [x] **Tier 1 on-device TFLite inference** — real latency measured on the Pi:
  model load 6 ms, inference **38.7 ms avg** (min 37.1 / max 41.1 over 10 runs).
  *Accuracy still unmeasured* — this is the stand-in model, not the real one.
- [x] **Tier 2 GPU inference server** — running on the RTX 5080
  (torch 2.11.0+cu128, capability 12.0/sm_120). Real Pi `GPUServerClassifier`
  → live server round-trips in **~26 ms** locally, ~1 s from the Pi over WiFi.
  Throughput testing deliberately skipped (personal project, latency is fine).
  *Real weights still outstanding* — see below.
- [x] **Tier chain handoff verified on hardware** — live capture → Tier 1 (0.05,
  under threshold) → Tier 2 (0.27, under threshold) → Tier 3 (backend offline,
  times out) → best-effort result retained. Exercises the confidence-threshold
  fallback end-to-end across a real LAN hop.
- [x] **GPIO sanity (C0–C2)** — `rpi-lgpio` shim confirmed on RP1; BCM17 output
  toggle and internal pull-up/pull-down readbacks all correct.
- [ ] Trigger peripheral (C3 loopback / C4 real sensor) — needs a jumper or a
  physical PIR / IR-beam sensor.
- [ ] **Real model weights** — both tiers currently run stand-ins (Tier 1: the
  generated `stand_in_smoketest_224_uint8.tflite`; Tier 2: `tf_efficientnet_b4`
  with a randomly-initialised 20-class head). Every label produced so far is
  meaningless by construction. This is now the single biggest gap.
- [x] **Backend + Postgres on the gaming PC** — `docker compose up` (after
  fixing the container, which had never been able to boot). Real multipart
  `POST /sightings` from the Pi lands a 300 KB camera JPEG in Postgres as
  `bytea`; `GET /sightings/{id}/image` returns it byte-identical under a user
  JWT and 401s without one.
- [ ] **Tier 3 on hardware** — reached the backend and got a clean 503 because
  `CLAUDE_API_KEY` is unset. Set the key to actually exercise the Claude relay.
- [ ] Full field test: live bird → capture → classify → sighting → notification.

**Exit criteria:** a real visit at the feeder produces a correct, notified sighting in the web app.

> **Bring-up session 2026-07-24:** plumbing is proven end-to-end on real
> hardware; what remains is *substance* (real weights, a trigger sensor, the
> backend up). Four defects were found and fixed along the way — see
> `HARDWARE_TEST_PLAN.md` §6.

---

> ## 🪺 The nest below is still building
>
> **Phase 4 is parked** until the Pi and RTX 5080 are on the bench. Everything
> from **Phase 5 on is ☁️ cloud/mobile work** — no hardware required — so the
> app keeps maturing while the feeder roosts. Phase 4 keeps its number (it's
> still *the* hardware pass, whenever it lands); the phases below can all ship
> before it.

---

## Phase 5 — 🦜 Decoy  ·  Device Simulator & Demo Mode  ☁️

*Stand in for the Pi. A fake feeder that drives the whole pipeline so every
screen, notification, and stat can be seen and verified — from a phone.*

The static `backend/seed.py` gives a snapshot; this gives a **living** feed. It
turns "I can't test the app without hardware" into "the app is always
demonstrable."

- [ ] **Virtual device / sighting generator** — a script (`backend/simulator.py`
  or `scripts/simulate.py`) that authenticates as a device token and posts
  realistic sightings to `POST /sightings` on an interval: rotating species from
  `taxonomy.csv`, plausible confidence per tier, day/night visit weighting, and a
  small bank of placeholder bird images.
- [ ] **Continuous vs. burst modes** — one-shot backfill (N sightings over the
  last M days) for populating history, and a live drip (one every few seconds)
  to watch the dashboard, notifications, and "online" device status update in
  real time.
- [ ] **Demo Mode toggle** — an env-gated, read-only demo seed + a banner in the
  frontend so a fresh clone (or a reviewer on their phone) lands on a populated,
  clickable app with zero setup.
- [ ] Contract-align the simulator with the real Pi client so it exercises the
  exact `POST /sightings` multipart shape the hardware will use (reuse the
  Phase 3 seam).

**Exit criteria:** `python -m backend.simulator` populates a running stack and
you can watch a sighting flow end-to-end — capture → classify → gallery →
notification — on a phone, with no Pi in the loop.

---

## Phase 6 — 📊 Census  ·  Analytics, Insights & Export  ☁️

*Turn the sightings table into something worth checking daily. Pure
data/backend + charts — all cloud.*

- [x] **Richer dashboard analytics** — `GET /stats/insights` over a selectable
  window (clamped 1–365): visits-per-day trend, hour-of-day histogram,
  cumulative species diversity, new-species arrivals, longest active-day streak,
  and a per-device breakdown. "New" means the species' *all-time* first sighting
  falls in the window, not merely its first sighting within it.
- [x] **Frontend charts** — an Insights section on the Dashboard with a time
  range + station filter row scoping everything below it. Built to the `dataviz`
  method: brand hue angles snapped into the charting lightness band and
  **validated** (CVD separation, normal-vision floor, ≥3:1 contrast, at
  `--pairs all`) for light *and* dark, dark steps selected rather than flipped.
  Single-hue marks (identity lives on the axis), 2px lines, 24px-capped bars
  with rounded data-ends, crosshair + per-mark tooltips, keyboard focus parity,
  and a table view on every chart so no value is gated behind a pointer.
- [x] **Data export** — `GET /sightings/export` (CSV/JSON, auth-scoped, served
  as an attachment) plus Export CSV/JSON actions in the filter row. Rows join
  species and device names so the file reads standalone; image bytes are
  excluded in favour of an `image_url` per row.
- [x] **Species enrichment** — cached description (Wikipedia summary extract,
  free in the request already being made for the URL) and taxonomy family/order
  (GBIF, keyless). Fills only empty columns so curated values survive.
  Conservation status intentionally skipped — IUCN needs a registered key and
  GBIF's threat status is sparse for backyard birds.

**Exit criteria:** the Dashboard answers "what's been happening at the feeder?"
at a glance, and a user can export their sighting history in one click. Covered
by unit tests over the new aggregate queries + export serialization. ✅
*(24 backend tests for insights/export, 14 for enrichment, 9 frontend chart
tests; verified in the browser against the real 135-sighting dataset in both
themes.)*

---

## Phase 7 — 📱 Perch  ·  PWA & Mobile Experience  ☁️

*A native app is a v1 non-goal (PRD §3) — a PWA closes most of that gap and is
exactly what pays off "while on mobile."*

- [ ] **Installable PWA** — web app manifest (icons, name, theme color), a
  service worker for offline shell caching, and "Add to Home Screen" support.
- [ ] **Offline-tolerant reads** — cache the last-loaded sightings/species so the
  app opens to content on a flaky connection (write paths stay online-only).
- [ ] **Web push notifications** — opt-in browser push for new sightings as a
  fourth delivery channel alongside email/SMS, wired into the existing
  fire-and-forget notification service (mockable in CI).
- [ ] **Mobile-first polish** — build on the Phase 2 off-canvas nav: touch-target
  sizing, pull-to-refresh on the feed, image lazy-loading, and lighthouse/PWA
  audit fixes.

**Exit criteria:** Peck Deck installs to a phone home screen, opens offline to
cached content, and can push a new-sighting alert — verifiable against the
Phase 5 simulator with no hardware.

---

## Phase 8 — 🛡️ Roost  ·  Production Readiness & Security  ☁️

*Make it safe to actually run. All static-analysis / config / test work — cloud.*

- [x] **Security pass** — closed a live **privilege escalation**: `POST /users`
  had no guard and `role` was client-supplied, so anyone could mint an owner
  account and enumerate every user's email and phone. Now owner-only with a
  validated role. Added per-account **and** per-IP login throttling (5 / 5 min →
  429 + `Retry-After`), an explicit CORS allowlist (`*` rejected while
  credentials are allowed), a 15 MB request-body cap, and a production boot
  check that refuses default/short `JWT_SECRET` or wildcard CORS. Dependency
  audits (`pip-audit` + `npm audit`) run in CI; the 6 npm findings were cleared
  by upgrading to vite 8 / vitest 4.
- [x] **Database migrations** — Alembic replaces `create_tables()` at boot
  (which only ever created *missing* tables, so model changes never reached the
  database). Baseline verified against a `pg_dump` of the `create_all` schema;
  `scripts/migrate.sh` entrypoint; the container migrates before serving; and
  `integration_tests/test_migrations.py` fails CI if models drift from
  migrations.
- [x] **Health & readiness** — `/health` stays dependency-free (liveness);
  new `/ready` checks DB connectivity **and** migration state, 503 when not
  ready. The compose healthcheck targets `/ready`.
- [x] **Backup & restore** — `scripts/backup.sh` / `restore.sh` (pg_dump `-Fc`
  from inside the db container) plus `backup_smoke_test.sh`, which restores into
  a throwaway database and compares row counts **and a SHA-256 of the image
  bytes** — a backup that restored rows but truncated `bytea` would lose every
  photo unnoticed.
- [x] **API docs** — OpenAPI schema at `/schema` (interactive) and
  `/schema/openapi.json`, with both auth schemes documented. Snapshot committed
  to `docs/openapi.json` via `scripts/export_openapi.py` so contract changes
  appear in review diffs.

**Exit criteria:** a clean security review, versioned migrations, a readiness
probe orchestration can trust, and a documented backup path — the stack is
deployable, not just runnable. ✅

> **Also fixed during this phase** (not originally scoped): notifications were
> silently dropped for the first `min_interval_seconds` of process uptime —
> `time.monotonic()` counts from boot, so the throttle suppressed every *first*
> notification after a reboot. This was also why CI had been red on `main` since
> Phase 0. Separately, the Phase 1 error envelope dropped `exc.headers`,
> swallowing `Retry-After` and `WWW-Authenticate`.

---

## Suggested order

`Phase 0` → `Phase 1` ↔ `Phase 2` (parallelizable) → `Phase 3` →
**`Phase 5` ↔ `Phase 6` ↔ `Phase 7` ↔ `Phase 8`** (all ☁️, do from mobile) →
`Phase 4` (🔌 hardware, whenever the bench is ready).

Phase 0 first: CI + accurate docs make every later phase safer and faster. Phases 1
and 2 are independent and can leapfrog based on what you feel like building. Phase 3
ties them together. **Phase 5 is the unlock for the rest** — a simulator means
Phases 6–8 (and even a dry-run of Phase 4's flow) are all visually verifiable from
a phone. Phases 6, 7, and 8 are independent of each other; pick by mood. Phase 4
still waits for the hardware — by then everything feeding into it is proven twice
over: once by the tests, once by the simulator.

---

*Each checkbox is a candidate unit of work / PR. Tackle them one at a time from
mobile; CI (Phase 0) keeps `main` honest the whole way.*
