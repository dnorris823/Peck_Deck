# Peck Deck — Claude Code Instructions

## Writing

These rules apply to every word written for a human to read. Chat replies, GitHub
issue bodies and comments, pull request text, commit messages, docs, and code
comments. They override the default style of any skill, including `/wayfinder`,
`/grilling`, and `/research`.

They do not apply to code identifiers, quoted material, command output, or
existing text nobody asked to change.

The rules merge two sources. ASD-STE100 Simplified Technical English supplies the
sentence discipline. Poteto's `unslop` supplies the pattern list and the voice
guidance. Take the STE rules, not the STE controlled vocabulary. Domain terms stay.

### Sentences

- One idea per sentence. Split any sentence that makes the reader backtrack.
- About 20 words per sentence for instructions. About 25 for explanation.
- Six sentences per paragraph at most.
- Active voice. Name the actor. Write "the worker drains the queue", not "the
  queue is drained". Passive is fine only when the actor is unknown.
- Simple tenses. No stacked participles.
- Three words at most in a noun cluster.

### Punctuation

- No em dashes. End the sentence or use a comma. Do not substitute parentheses,
  en dashes, or a hyphen standing in for a dash.
- Colons introduce a list or an example. Never use one as a mid-sentence connector.
- Straight quotes, not curly.

### Words

- Use the plain word. Use, not utilize. Help, not facilitate. Many, not numerous.
- One term per thing. Never cycle synonyms for variety.
- No abstract metaphor nouns. Substrate, wedge, vector, nexus, primitive, harness,
  surface, bedrock, scaffolding, north star, flywheel, load-bearing. Name the
  mechanism instead.
- No AI vocabulary. Additionally, crucial, delve, enhance, fostering, garner,
  intricate, landscape, pivotal, showcase, tapestry, testament, underscore, vibrant.
- Say "is" or "has". Not "serves as", "stands as", "boasts", "features".
- Cut adverbs. An adverb propping up a weak verb means the verb is wrong. Give the
  number instead of "significantly faster".
- Cut filler. "In order to" is "to". Delete "it is important to note that".
- Cut stacked hedges. "Could potentially possibly" is "may".
- No "not just X, but Y". State the point.

### Shape

- Answer first. Reasons second.
- Tables and lists carry structure. Prose carries argument.
- Sentence case headings. No decorative emoji.
- Do not bold every proper noun or acronym.
- A bold label that restates the line is a tell. A bold lead-in that names the item
  and is followed by new detail is fine.
- Say what a thing does, not how it feels. Name the mechanism, the file, or the
  number. If a sentence would fit another project unchanged, cut it.

### Voice

- Have an opinion. React to the facts instead of listing both sides evenly.
- Be specific. Name the number, the file, the failure mode.
- No chatbot phrases, no sycophancy, no generic conclusions.

### When the two sources conflict

STE wants uniform short sentences. `unslop` wants varied rhythm and human voice.

| Artifact | Which wins |
|---|---|
| Issues, specs, decision records, commit messages, docs | STE discipline. Short and uniform. |
| Chat replies, and any text that argues a position | Vary sentence length. Keep every word and punctuation rule. |

Both always share active voice, one idea per sentence, plain words, no em dashes,
and no filler.

### Two points specific to this repo

- There is no `CONTEXT.md` yet. Until `/domain-modeling` creates one, take terms
  from `PRD.md`, `MODELS.md`, and this file. Do not invent a synonym for a term the
  code already uses. Say "tier", "escalation", "sighting", "visit", "capture", and
  "device" the way the code says them.
- Wayfinder tickets name each other constantly. Write the ticket title as the link
  text. A bare `#42` is unreadable in a list of twenty.

A private copy of these rules also lives in the user's `~/.claude/CLAUDE.md`. This
file is the shared one, so keep it authoritative for the repo.

## What is this project

Peck Deck is a smart bird feeder. A Raspberry Pi 5 with a camera detects bird
visits, captures images, classifies the species through one of three ML tiers,
and notifies users. A React web app and a Python backend on a home gaming PC are
the management hub.

`PRD.md` has the requirements. `FLEDGE_ROADMAP.md` says what is built and what is
open. Phase 4, hardware bring-up, is the only phase still open.

## Read these when the work touches them

| Topic | File |
|---|---|
| Live updates over SSE | `docs/live-updates-sse.md` |
| Simulator and demo mode | `docs/simulator-and-demo-mode.md` |
| PWA and web push | `docs/pwa-and-web-push.md` |
| Backups, migrations, health, OpenAPI, test suites | `docs/operations.md` |
| Running anything locally | `CONTRIBUTING.md` |
| Pi setup | `SETUP.md` |
| Model provenance and measured accuracy | `machine_learning/MODELS.md` |
| Agent conventions | `AGENTS.md`, `docs/agents/` |

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
  never evicted, and neither is the capture being classified. `MAX_CACHE_IMAGES`
  bounds unqueued images only. `MAX_QUEUED_SIGHTINGS` bounds the backlog.
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

Tier 1 runs TFLite on the Pi. Tier 2 is the LAN GPU server at `POST /classify`.
Tier 3 relays through the backend to the Claude API. The Pi falls back from 1 to 2
to 3 on availability and confidence.

**Thresholds are per tier, and measured.** `DEFAULT_TIER_THRESHOLDS` in
`raspberry_pi_code/config.py` holds local 0.85, gpu 0.60, cloud 0.50. A single 0.5
across all three accepted the wrong species 18.2% of the time on Tier 1, silently,
because a confidently wrong tier never escalates. They differ per tier for two
reasons. The numbers are not comparable, since Tier 2 softmaxes over 10,000
classes against Tier 1's 965. And the escalations cost differently, since Tier 1
escalates to a free LAN GPU while Tier 2 escalates to a paid Claude call. Override
with `TIER1_/TIER2_/TIER3_CONFIDENCE_THRESHOLD`. The legacy global
`CONFIDENCE_THRESHOLD` still wins where it is set, and logs a warning saying so.

**Tiers 1 and 2 share one label space**, `machine_learning/taxonomy.csv`. Tier 1
indexes into it directly. Tier 2 projects its own 10,000 classes onto it by
scientific name, and 869 of them map. That is what makes the two answers
comparable. Row order **is** the index contract. Regenerate the file, never
hand-edit it.

Accuracy claims belong in `machine_learning/MODELS.md` under *Measured accuracy*.
Measure one tier with `scripts/validate_tiers.py` and the whole chain with
`scripts/simulate_tier_chain.py`. **Do not use `validate_tier1.py`.** It is a
20-image wiring check on clean photos, and it will report 100% for both tiers
forever.

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
- **The allowlist in `backend/demo.py` is the whole security boundary for demo
  mode.** It runs as ASGI middleware, before any guard, so it decides on method and
  path alone. A new device-facing route has to be added there too.
- **The VAPID public key is derived from the private key**, never read from
  `VAPID_PUBLIC_KEY`. A mismatched pair fails only at delivery time, on every send.
  Never rotate the keypair, because browsers bake the public key into their
  subscriptions.
- The service worker only registers in a production build, so `npm run build`
  comes before any PWA or push testing.

## Health endpoints

`GET /health` checks nothing, deliberately, so a database blip never restarts a
healthy container. `GET /ready` checks the database and the migration revision, and
the compose healthcheck targets it. `GET /meta` is public and reports `demo_mode`.
Detail in `docs/operations.md`.

## Agent skills

Configuration for the `mattpocock-skills` engineering skills. Nothing else reads
these files.

- Issues live in GitHub Issues on `dnorris823/Peck_Deck`, driven by the `gh` CLI.
  See `docs/agents/issue-tracker.md`.
- Triage labels keep their five default names. See `docs/agents/triage-labels.md`.
- Domain docs are single-context: one `CONTEXT.md` at the root plus `docs/adr/`.
  Neither exists yet, and `/domain-modeling` creates them lazily. See
  `docs/agents/domain.md`.
