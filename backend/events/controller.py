"""``GET /events`` — a Server-Sent Events stream of new sightings.

Replaces polling. The web app loads its dataset once and then holds this stream
open; a new visit arrives as a message carrying the sighting row itself, so the
feed updates with no refetch at all and only the (small) aggregate endpoints are
re-read. Polling the full dataset every 30s cost ~1,080 requests and ~4.3 MB per
hour per open tab to discover the two or three visits an hour a feeder actually
produces.

**Why SSE and not WebSockets.** The data only ever flows server → client, so a
bidirectional protocol would buy nothing and cost a protocol upgrade, proxy
configuration and a hand-rolled heartbeat. This is plain HTTP: it goes through
the Vite ``/api`` proxy and the existing CORS allowlist unchanged.

**Why the client doesn't use ``EventSource``.** It cannot send an
``Authorization`` header, and every route here is Bearer-JWT. Putting a token in
the query string would leak it into access logs, and switching to cookie auth to
suit one endpoint is the tail wagging the dog — so the browser reads this with
``fetch`` and parses the framing itself (``frontend/src/events.js``), which
keeps the header and leaves the auth model alone.

Three things this has to get right beyond "send the row":

* **Scope.** A subscriber is only sent sightings from devices it can access.
  The set is resolved once, at connect, from the same helper the REST routes
  use — so a device shared with a user mid-stream is picked up on their next
  reconnect, not immediately.
* **Gaps.** ``Last-Event-ID`` is honoured, so a dropped connection replays what
  it missed instead of leaving a hole in the feed until the next manual reload.
* **Database connections.** The stream deliberately does **not** take the
  request-scoped ``db`` dependency: that opens a session *and* a transaction for
  the life of the request, and an SSE request lives for hours. It would pin a
  pooled connection and leave Postgres idle-in-transaction per open tab. Short
  sessions are opened for the connect-time work and closed before streaming
  begins; the stream itself touches no database at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import asdict

from litestar import Controller, Request, get
from litestar.response import ServerSentEvent, ServerSentEventMessage
from sqlalchemy import select

from ..auth.guards import user_guard
from ..database.connection import get_session_factory
from ..database.models import Sighting
from ..sightings.operations import _accessible_device_ids
from ..sightings.schemas import sighting_response
from .hub import RESYNC, SightingEvent, sighting_hub

logger = logging.getLogger("peckdeck.events")

# Sent when the stream is otherwise idle. Not decoration: an idle connection is
# indistinguishable from a dead one to any proxy between here and the browser,
# and several will close it silently at 60s. This also gives the client its own
# liveness signal, so it can reconnect rather than sit on a socket nothing is
# coming down.
HEARTBEAT_SECONDS = 25

# Cap on a Last-Event-ID replay. Past this, a reconnecting client is told to
# refetch: 500 individual messages is both slower and larger than the ~37 KB
# full load it is trying to avoid.
MAX_REPLAY = 200


async def _missed_since(last_event_id: int, device_ids: list[int]) -> list[dict] | None:
    """Sightings newer than ``last_event_id``, oldest first.

    ``None`` means "too many to replay" — the caller turns that into a resync.
    """
    async with get_session_factory()() as db:
        result = await db.execute(
            select(Sighting)
            .where(Sighting.id > last_event_id, Sighting.device_id.in_(device_ids))
            .order_by(Sighting.id.asc())
            .limit(MAX_REPLAY + 1)
        )
        rows = list(result.scalars().all())

    if len(rows) > MAX_REPLAY:
        return None
    return [_wire(s) for s in rows]


def _wire(sighting) -> dict:
    return asdict(sighting_response(sighting))


def _parse_last_event_id(raw: str | None) -> int | None:
    """A client-supplied header — treat anything unparseable as absent."""
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class EventController(Controller):
    path = "/events"

    @get("/", guards=[user_guard])
    async def stream(self, request: Request) -> ServerSentEvent:
        user_id = request.state.user_id
        last_event_id = _parse_last_event_id(request.headers.get("Last-Event-ID"))

        return ServerSentEvent(
            _generate(user_id, last_event_id),
            # Proxies that buffer a response defeat the entire point; nginx in
            # particular needs telling explicitly.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


async def _generate(
    user_id: int, last_event_id: int | None
) -> AsyncGenerator[ServerSentEventMessage, None]:
    """The stream body: subscribe, catch up, then forward until disconnect."""
    # Subscribe *before* the replay query, so a sighting written between the two
    # is queued rather than lost. It may then arrive twice; the client dedupes
    # by id, which is the cheap side of that trade.
    async with sighting_hub.subscribe() as queue:
        async with get_session_factory()() as db:
            device_ids = await _accessible_device_ids(db, user_id)

        # A user with no stations still gets a live stream — they may be granted
        # one while connected — but nothing can currently match, so skip replay.
        if last_event_id is not None and device_ids:
            missed = await _missed_since(last_event_id, device_ids)
            if missed is None:
                yield ServerSentEventMessage(event="resync", data="too_far_behind")
            else:
                for payload in missed:
                    yield ServerSentEventMessage(
                        event="sighting", id=payload["id"], data=json.dumps(payload)
                    )

        # Tells the client it is live, and carries the retry interval the browser
        # should use if this connection drops.
        yield ServerSentEventMessage(event="ready", data="ok", retry=3000)

        logger.info(
            "SSE stream opened for user %d (%d device(s), %d subscriber(s))",
            user_id, len(device_ids), sighting_hub.subscriber_count,
        )

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ServerSentEventMessage(comment="keepalive")
                    continue

                if item is RESYNC:
                    yield ServerSentEventMessage(event="resync", data="overflow")
                    continue

                assert isinstance(item, SightingEvent)
                if item.device_id not in device_ids:
                    continue
                yield ServerSentEventMessage(
                    event="sighting",
                    id=item.sighting_id,
                    data=json.dumps(item.payload),
                )
        except asyncio.CancelledError:
            # The normal way a stream ends: the client went away and Litestar
            # cancelled the generator. Not an error.
            logger.info("SSE stream closed for user %d", user_id)
            raise
