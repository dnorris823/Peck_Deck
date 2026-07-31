"""In-process fan-out of "a sighting happened" to connected SSE streams.

The web app used to learn about new visits only by refetching its whole dataset
— nine requests, ~37 KB — so seeing a feeder in something like real time meant
polling that every few seconds to discover the two or three visits an hour a
real feeder actually produces. This is the other half of ``GET /events``: the
publish side.

**Deliberately in-process.** With the single ``api`` container this repo ships,
one asyncio fan-out is the whole job and a message bus would be theatre. The
moment there are two API processes it stops being sufficient — a browser
attached to process A will never see a sighting written by process B, silently.
The fix then is Postgres ``LISTEN/NOTIFY`` (asyncpg has ``add_listener``, and
the database is already the one thing both processes share) behind this same
:meth:`SightingHub.publish` / :meth:`SightingHub.subscribe` pair, so nothing
upstream or downstream has to change. See ``CLAUDE.md``.

Two rules the publisher side must keep, because it runs on the Pi's upload path:

* **Never block.** ``publish`` is synchronous and uses ``put_nowait``. Uploading
  a sighting must not wait on a browser reading its socket.
* **Never raise.** A failure to notify a watching tab is not a failed upload.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("peckdeck.events")

# Per-subscriber backlog. A browser that stops reading (a suspended phone, a
# laptop lid) must not grow an unbounded queue in the API process. Sized well
# above any plausible burst: past this the connection is told to resync rather
# than fed a backlog it can't catch up on.
MAX_PENDING = 64

# Sentinel queued in place of an event when a subscriber has overflowed. The
# stream turns it into a `resync` message, and the client refetches — which is
# correct *and* cheaper than replaying a long backlog one event at a time.
RESYNC = object()


@dataclass(frozen=True)
class SightingEvent:
    """One new sighting, already serialized for the wire.

    The payload is built once by the publisher rather than re-read per
    subscriber: the row is in hand at publish time, and N connected tabs should
    not mean N queries for a row that was just written.

    ``device_id`` is carried outside the payload because it is what every
    subscriber filters on, and reaching into the dict to route would be worse.
    """

    sighting_id: int
    device_id: int
    payload: dict[str, Any]


class SightingHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: SightingEvent) -> None:
        """Hand an event to every open stream. Never blocks, never raises."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the backlog and ask for a full refetch instead. Draining
                # first is what keeps RESYNC itself from hitting a full queue.
                _drain(queue)
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(RESYNC)
                logger.warning(
                    "SSE subscriber fell more than %d events behind; asked it to resync",
                    MAX_PENDING,
                )
            except Exception:  # pragma: no cover - defensive
                # Nothing about notifying a browser is worth failing an upload.
                logger.exception("failed to publish sighting event")

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        """Register a queue for the life of one stream, and always clean it up.

        A context manager rather than add/remove calls because the removal is
        the part that matters: a generator abandoned when the client disconnects
        must not leave its queue in the set, collecting events forever.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_PENDING)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


def _drain(queue: asyncio.Queue) -> None:
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return


# Module-level singleton: one hub per API process, which is exactly the scope
# an in-process fan-out has.
sighting_hub = SightingHub()
