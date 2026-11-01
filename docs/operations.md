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
species no longer points at "Unknown", so the rule skips it. So is a sighting
still waiting for the Tier 2 re-check, because the GPU may yet name it.

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

## Tier 2 re-check

When the inference server is off, the Pi falls back to Tier 1 and the sighting
appears at once, marked provisional. The API process then re-checks it on the
GPU once the server answers again. The code is in `backend/sightings/recheck.py`.

| Env var | Default | Effect |
|---|---|---|
| `INFERENCE_SERVER_URL` | `http://host.docker.internal:8001` | Where the API reaches the inference server. The default reaches the host from the `api` container. |
| `TIER2_RECHECK_INTERVAL_SECONDS` | `60` | How often the task looks for waiting sightings and calls `GET /health`. `0` turns the re-check off. A negative value refuses to start. |
| `TIER2_ANIMAL_THRESHOLD` | `0.30` | The bar for Tier 2's animal answer. Keep it equal to the Pi's `TIER2_ANIMAL_THRESHOLD`. |

- The upload marks a sighting pending when its trace shows Tier 2 `failed`, or
  shows every tier `not_run` with tier `none`. A sighting with no trace, or
  with no Tier 2 entry, is never re-checked.
- Sightings created before this change are never re-checked. Their
  `tier2_recheck` is null.
- A pass sends pending captures to `POST /classify` one at a time, oldest first.
  It sends the square the Pi classified, from the upload's `crop_box`, or the
  full frame without one.
- Tier 2 replaces the species when it meets the `gpu` threshold from the
  sighting's trace. Below it, the answer closer to its own tier's bar wins.
  `provisional_species_id` keeps the Pi's species.
- A feeder animal wins first, by the Pi's rule. It meets `TIER2_ANIMAL_THRESHOLD`
  and beats Tier 2's bird. The sighting then takes the animal species, with
  `kind = 'animal'` and its group, whatever Tier 1 said. Tier 1 knows birds
  only, so a squirrel caught with the 5080 off is a Tier 1 bird until then.
- A connection error, a timeout or a 5xx ends the pass, and the rows stay
  pending. A 4xx marks that one row done with no change.
- A sighting a person corrected keeps their species.
- `tier_trace` stays as the Pi wrote it, so the Tier 2 warning still sees the
  outage.
- A re-check sends no normal alert, because the upload sent one. It sends the
  new species alert, which waits for the re-check. See *New species alerts*
  in `docs/pwa-and-web-push.md`. Open tabs update over SSE.
- The task assumes one API process. Two would re-check a row twice.

Each pass that finds the server logs `tier2 recheck: server is up, re-checking
N sightings`, then one line per sighting.

## Gaming pause

The inference server unloads the Tier 2 model while a game runs, so the game
gets the 5080's VRAM. The code is in `inference_server/gaming.py`.

`GET /health` on the inference server reports one state:

| State | Meaning |
|---|---|
| `ready` | The model is loaded. `POST /classify` answers. |
| `loading` | The model is loading, about 4 s from the local cache. |
| `paused_game` | The server saw a game and unloaded the model. |
| `paused_manual` | The owner turned Tier 2 off. Only the owner turns it on. |
| `failed` | The model did not load. A resume tries again. |

While the state is not `ready`, `POST /classify` returns 503 with the reason.
The Pi falls back to Tier 1, as it does when the server is off. The upload's
trace shows Tier 2 `failed`, so the backend marks the sighting pending, and the
re-check holds it until the state is `ready`. Then Tier 2 names it.

**Automatic pause.** The server reads GPU use through NVML every
`GAME_SAMPLE_SECONDS`. It goes by GPU use alone. On Windows, NVML lists the
desktop compositor and every browser as holding a graphics context, so a
graphics context cannot tell a game from the desktop. Readings taken within 2 s
of the server's own classify call are skipped, so a re-check backlog never
pauses Tier 2.

| Env var | Default | Effect |
|---|---|---|
| `GAME_PAUSE_ENABLED` | `true` | `false` turns the automatic pause off. The owner's switch still works. |
| `GAME_PAUSE_PERCENT` | `50` | Pause when mean GPU use over the pause period reaches this. |
| `GAME_PAUSE_AFTER_SECONDS` | `30` | The pause period. |
| `GAME_RESUME_PERCENT` | `15` | Resume when mean GPU use over the resume period is at or below this. Must be below `GAME_PAUSE_PERCENT`. |
| `GAME_RESUME_AFTER_SECONDS` | `300` | The resume period. |
| `GAME_SAMPLE_SECONDS` | `2` | How often the server reads GPU use. |

The automatic pause needs `nvidia-ml-py`, in `inference_server/requirements.txt`.
Without it the server logs `NVML not available` and never pauses itself.
`game_pause` in `GET /health` says whether the watcher runs.

**The owner's switch.** The Feeders page has a Tier 2 switch. The backend relays
it through `PUT /tier2`, owner only, to `POST /pause` or `POST /resume` on the
inference server. `GET /tier2` reads the state for any signed-in user, and says
`offline` when the server does not answer.

- Turning Tier 2 off sets `paused_manual`. The server stays paused after the
  game, until the owner turns it on.
- Turning Tier 2 on during a game loads the model, and the server does not pause
  for that game again. The hold ends when GPU use falls below
  `GAME_PAUSE_PERCENT`, so the next game pauses it.
- A restart loads the model. A pause is not saved.

**Motion captures are dropped while Tier 2 is paused.** A motion capture needs
Tier 2 to name a bird or an animal, and Tier 1 is never asked. The Pi drops it,
as it does when the server is off. A bird the camera detected is never dropped.

Home and the feeder card say "Tier 2 paused for gaming" in place of the Tier 2
down warning.

The control endpoints have no auth, like `POST /classify`. Anyone on the LAN can
pause Tier 2.

## Feed alerts

The API process checks every feeder once at startup and then every hour. The
check warns the feeder's owner by email and push when the feed is probably low
or out. The code is in `backend/feed/`.

| Env var | Default | Effect |
|---|---|---|
| `FEED_ALERTS_ENABLED` | `true` | `false` starts no task and sends no feed alerts. |

Visits are bird sightings only, through `is_bird_sighting()`. "Unknown" captures
count, because their species row is a bird. Animal visits do not. A squirrel that
keeps checking an empty feeder would otherwise hold the count up and hide `out`,
and a raccoon at night would raise the night baseline.

Two rules can raise an alert:

| State | Rule | Ends at |
|---|---|---|
| `out` | The last 3 hours have at most a quarter of the visits the same 3 hours averaged over the past 14 days. The rule needs an average of 6 or more, so night hours stay silent. | The next refill, or visits back to half the average. |
| `low` | Visits since the last refill reach 85% of the median visits per fill. The median needs 3 measured fills of the same feed type. | The next refill, or an `out` alert. |

The owner gets one alert when a state starts, and none while it lasts.
`GET /devices` returns the state in `feed`.

The `out` rule does not run in these cases:

- The feeder is offline, or came back from an outage less than 3 hours ago.
  The backend logs each outage in `device_outages` when the device reaches it
  again.
- The Pi's heartbeat has no camera trigger tick from the last 10 minutes. The
  Pi sends `trigger_age_seconds`, the seconds since the trigger analysed a
  frame, from `CameraTrigger.tick_age()`. Every analysed frame counts, whatever
  the detector found. A heartbeat without the field means the trigger is not
  running.
- The owner logged a refill, and no check since has seen normal visits. Birds
  can take days to find a refilled feeder.

The 14-day average leaves out past windows that overlap an outage or an `out`
spell. A feeder needs 7 usable days of visits before the rule runs. The numbers
are first guesses. Tune them in `backend/feed/rules.py` once the Pi is at the
window.

## Animal visits

Tier 2 names the feeder mammals in `machine_learning/feeder_animals.csv`. The
sighting's species has `kind = 'animal'` and an `animal_group`, such as
`squirrel`. Every bird count leaves animal sightings out through
`is_bird_sighting()`. The code is in `backend/animals/`.

### Measures

An owner logs what they did to keep animals off, such as "Baffle on the pole".
The routes are `GET`, `POST`, `PATCH` and `DELETE /devices/{id}/measures`. Anyone
who can see the feeder can list them. Only the feeder's owner or an owner-role
user can change them. `PATCH` with `ended_at` ends a measure, and an empty
`ended_at` puts it back in place.

`GET /stats/animals?device_id=&from_date=&to_date=&tz=` returns animal visits per
local day and group, the bird count for each day, and each measure in range with
its effect:

- Animal visits per group in the 14 days before `started_at`, and in the days
  after, up to 14, or to `ended_at` if sooner.
- Each count divided by the camera-up hours in its window. The hours a feeder
  was offline come out, by the feed alerts' rule: each `device_outages` row, and
  the time since `last_seen` while the feeder is offline now. The hours before
  the feeder's first sighting come out too.
- The after rate over the before rate, with a 95% interval. The log of the ratio
  has a standard error of `sqrt(1/a + 1/b)`. With a zero count the interval is
  null.
- The bird rate over the same two windows. If birds fell by the same share, the
  cause was weather or empty feed, not the measure.

One feeder has no control group, and animal activity changes with the season.
The Animals view says "after", never "because of".

### Animal alerts

Each user has a push switch per animal group in `user_preferences.animal_alerts`.
Squirrel, raccoon, bear and cat are on by default. Chipmunk, rat, rabbit, opossum
and deer are off. Animal alerts are push only. The throttle key is (user,
feeder, group), with `animal_quiet_interval_seconds`, 1800 by default. It is
apart from the bird throttle, so a squirrel never mutes a bird alert. It is
apart from the feed alerts too, which count birds only. The push `tag` is
`peckdeck-device-{id}-animal-{group}`, so a repeat replaces the last alert.

### Species rows

The migration `7a2d9e4b1c60` seeds one species row per feeder animal, so a
person can correct a sighting to a squirrel before any squirrel upload exists.
The backend keeps its own copy of the list in `backend/animals/groups.py`, for
the dev seed and the tests, because the image holds only `backend/`. A test keeps
it equal to the CSV.

## Pi backlog and vitals

Each heartbeat carries the Pi's offline queue and two vitals. The Feeders card
shows them. All five fields are optional, so an older Pi still sends a valid
heartbeat.

| Field | What it is |
|---|---|
| `queued_sightings` | Sightings in the offline queue, waiting to upload |
| `oldest_queued_age_seconds` | Age of the oldest. The backend stores an instant |
| `dropped_since_boot` | Sightings lost since the Pi started |
| `disk_free_bytes` | Free space on the file system under `CACHE_DIR` |
| `cpu_temp_c` | From `/sys/class/thermal/thermal_zone0/temp` |

A drop is a real loss: a sighting the backend refused for good, a queued
sighting whose image is gone, or the oldest one pushed out of a full queue. A
motion capture that Tier 2 could not name is not a drop.

Each heartbeat replaces all five values. A missing one clears, so the card never
shows a stale queue. The card says "14 waiting to upload, oldest 3 h" while the
queue is not empty. It warns on any drop, under 1 GB free, or 80 °C and over.
The limits are `DISK_WARN_BYTES` and `CPU_TEMP_WARN_C` in
`backend/devices/operations.py`. None of this changes the feeder's status.

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
