# Live updates (SSE)

Moved out of `CLAUDE.md`. The short warnings stay there; this is the detail.

The web app used to load its dataset once on mount and never refetch, so a
running feeder changed nothing on screen until someone reloaded the page.
`GET /events` is a Server-Sent Events stream of new sightings; `DataContext`
holds it open for the life of the session.

| Piece | Where | Notes |
|---|---|---|
| Fan-out | `backend/events/hub.py` | In-process asyncio pub/sub. `publish()` is **sync, non-blocking and never raises** — it runs on the Pi's upload path, so a browser that stopped reading must not be able to slow or fail an upload. |
| Publish seam | `backend/sightings/aftercare.py` | The one "a sighting happened" hook, called by `POST /sightings`. |
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
- **`DELETE /sightings/{id}` publishes a `sighting_deleted` event** carrying only
  the id. It goes out from a background task, which Litestar runs after the
  response is sent and so after the `db` session commits. A tab's aggregate
  refetch therefore never counts the deleted row. The event has no SSE `id:`
  line, because replay selects ids above the resume point. A tab that was
  disconnected during a delete misses it, and its next full load drops the row.
- A subscriber's device scope is resolved **once, at connect**, so a device
  shared with a user mid-stream appears on their next reconnect.
