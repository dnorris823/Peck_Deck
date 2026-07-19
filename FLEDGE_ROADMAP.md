# 🪶 FLEDGE — Peck Deck Development Roadmap

> **Fledge** *(v.)* — when a young bird develops the feathers it needs to fly.
> This roadmap gets the *software* flight-ready while the *hardware* roosts.

A phased plan to finish everything that **doesn't** need the Raspberry Pi or the
RTX 5080 gaming PC in hand — so real progress ships from anywhere, including a
phone — then land the remaining hardware bring-up in one focused pass once you're
back at the bench.

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

- [ ] Integration tests via `docker compose` against the real `postgres:16` service (not just SQLite).
- [ ] Contract tests for the seams: Pi client ↔ backend (`POST /sightings` multipart), backend ↔ inference server (`POST /classify`, mocked GPU).
- [ ] Seed/demo dataset + reusable fixtures for local and CI runs.
- [ ] Add the compose-based integration job to CI (Postgres service container).

**Exit criteria:** a single command spins the stack and runs green end-to-end without any physical device.

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

## Suggested order

`Phase 0` → `Phase 1` ↔ `Phase 2` (parallelizable) → `Phase 3` → `Phase 4`.

Phase 0 first: CI + accurate docs make every later phase safer and faster. Phases 1
and 2 are independent and can leapfrog based on what you feel like building. Phase 3
ties them together. Phase 4 waits for the hardware — by then, everything feeding into
it is already proven.

---

*Each checkbox is a candidate unit of work / PR. Tackle them one at a time from
mobile; CI (Phase 0) keeps `main` honest the whole way.*
