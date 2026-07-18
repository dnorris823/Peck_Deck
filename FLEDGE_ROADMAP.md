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

- [ ] **Continuous Integration** — `.github/workflows/ci.yml`
  - Backend job: install `backend/requirements-dev.txt`, run `pytest` (SQLite-backed, no Postgres service needed).
  - Frontend job: `npm ci` + `npm run build` in `frontend/`.
  - Trigger on push + PR to `main`.
- [ ] **Doc refresh**
  - `CLAUDE.md`: mark frontend (M5) and Tier 3 (M6) as **built**; fix stale "SQLite" mentions to **PostgreSQL**.
  - `PRD.md`: resolve/annotate the two open questions (trigger peripheral, solar charging).
  - Verify `SETUP.md` + `.env.example` match the current stack.
- [ ] **Repo hygiene**
  - Recommend branch protection on `main` (require CI green before merge).
  - Add a short `CONTRIBUTING.md` describing the branch/PR flow.

**Exit criteria:** every push runs CI; a new contributor can go from clone → green tests using only the docs.

---

## Phase 1 — 🧹 Preen  ·  Backend Hardening (M7)  ☁️

*Smooth out the API's rough edges. All independently testable with mocks.*

- [ ] Expand test coverage on the untested paths:
  - Auth failures (bad token, expired JWT, wrong role, device-token vs user-JWT).
  - Offline-sync / delayed-sighting flow logic.
  - Wikipedia lookup fallback chain (API → search → scrape → null).
  - Notification min-interval throttle + fire-and-forget failure isolation.
- [ ] Consistent error envelopes and input validation across controllers.
- [ ] Structured logging (request IDs, tier-used, notification outcomes).
- [ ] **Tier 3 tuning** — refine the Claude prompt + structured-output schema; add tests that exercise the real Claude API and assert the JSON contract.

**Exit criteria:** coverage meaningfully up from the current 50 tests; error responses are uniform; Tier 3 returns a validated `{common_name, scientific_name, confidence}` every time.

---

## Phase 2 — 🎨 Plumage  ·  Frontend Polish (M5 → M7)  ☁️

*Make the web app feel finished. Node-only; runs in the cloud box.*

- [ ] Loading / error / empty states across Dashboard, Sightings, Species, Devices.
- [ ] Form validation (login, user/device settings, API-key management).
- [ ] **Frontend test setup** — add Vitest + React Testing Library (currently no test tooling) and cover `DataContext`, `api.js`, and key components.
- [ ] Accessibility pass (labels, focus, keyboard nav) and responsive/mobile layout.
- [ ] Wire remaining screens to live backend endpoints; confirm the Dusk dark theme end-to-end.

**Exit criteria:** no dead/placeholder states; frontend tests run in CI; app is usable on a phone-sized viewport.

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
