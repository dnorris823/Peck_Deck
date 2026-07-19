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

- [ ] Pi camera capture + trigger (PIR / IR beam) real runs; validate debounce.
- [ ] Tier 1 on-device TFLite inference — real latency/accuracy on the Pi.
- [ ] Tier 2 GPU inference server — load the real model on the RTX 5080, measure throughput.
- [ ] Execute `HARDWARE_TEST_PLAN.md` end-to-end.
- [ ] Full field test: live bird → capture → classify → sighting → notification.

**Exit criteria:** a real visit at the feeder produces a correct, notified sighting in the web app.

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

- [ ] **Richer dashboard analytics** — extend `backend/stats/` beyond the current
  dashboard/species-count/heatmap: visits-per-day trend, busiest hours, species
  diversity over time, first-seen / new-species-this-week, longest streaks.
- [ ] **Frontend charts** — wire the new aggregates into the Dashboard with
  accessible, theme-aware visualizations (see the `dataviz` skill), including a
  time-range selector and per-device breakdown.
- [ ] **Data export** — `GET /sightings/export` (CSV/JSON, auth-scoped) and a
  frontend "Export" action; optional per-species report.
- [ ] **Species enrichment** — go past the Wikipedia URL: cache a short
  description, taxonomy order/family, and (where a free API allows) conservation
  status, so the Species Library reads like a field guide.

**Exit criteria:** the Dashboard answers "what's been happening at the feeder?"
at a glance, and a user can export their sighting history in one click. Covered
by unit tests over the new aggregate queries + export serialization.

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

- [ ] **Security pass** — run `/security-review` and close findings: auth rate
  limiting / lockout on `/login`, CORS policy, JWT expiry + rotation, device-token
  handling, request-size limits on image upload, and a dependency audit
  (`pip-audit` / `npm audit`) wired into CI.
- [ ] **Database migrations** — introduce Alembic so schema changes are
  versioned instead of `create_tables()` at boot; add an initial baseline
  migration and a `scripts/migrate` entrypoint.
- [ ] **Health & readiness** — extend `/health` into a real readiness probe
  (DB connectivity, migration state) for container orchestration; document the
  compose healthchecks.
- [ ] **Backup & restore** — a documented `pg_dump`/restore flow for the
  `bytea`-backed media + records, with a smoke test.
- [ ] **API docs** — publish Litestar's generated OpenAPI schema and link it from
  the docs so the Pi/frontend contract is self-describing.

**Exit criteria:** a clean security review, versioned migrations, a readiness
probe orchestration can trust, and a documented backup path — the stack is
deployable, not just runnable.

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
