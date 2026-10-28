# Device simulator and demo mode

Moved out of `CLAUDE.md`. The short warnings stay there; this is the detail.

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
