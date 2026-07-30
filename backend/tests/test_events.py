"""GET /events — the SSE stream, and the hub behind it.

The stream itself is driven as an async generator rather than over HTTP: it
never completes by design, so a ``TestClient.get`` would simply hang. Driving
``_generate`` directly exercises the parts with actual logic in them — scoping,
Last-Event-ID replay, overflow, heartbeats — and the route wrapper around it is
three lines.

Nothing here writes a sighting. The suite's dataset is asserted by exact count
elsewhere, and every event these tests need can be published straight into the
hub without touching the database.
"""
import asyncio
import json

import pytest

from backend.events import controller as events
from backend.events.hub import MAX_PENDING, RESYNC, SightingEvent, SightingHub, sighting_hub


def _event(sighting_id: int, device_id: int) -> SightingEvent:
    return SightingEvent(
        sighting_id=sighting_id,
        device_id=device_id,
        payload={"id": sighting_id, "device_id": device_id, "species_id": 1},
    )


# ---------------------------------------------------------------------------
# The hub
# ---------------------------------------------------------------------------
def test_publish_reaches_every_subscriber():
    hub = SightingHub()

    async def scenario():
        async with hub.subscribe() as a, hub.subscribe() as b:
            hub.publish(_event(1, 1))
            return a.get_nowait(), b.get_nowait()

    a, b = asyncio.run(scenario())
    assert a.sighting_id == b.sighting_id == 1


def test_subscribers_are_removed_on_exit():
    """An abandoned stream must not leave a queue collecting events forever."""
    hub = SightingHub()

    async def scenario():
        async with hub.subscribe():
            assert hub.subscriber_count == 1
        return hub.subscriber_count

    assert asyncio.run(scenario()) == 0


def test_subscriber_is_removed_even_when_the_stream_raises():
    hub = SightingHub()

    async def scenario():
        with pytest.raises(RuntimeError):
            async with hub.subscribe():
                raise RuntimeError("client vanished")
        return hub.subscriber_count

    assert asyncio.run(scenario()) == 0


def test_publish_never_blocks_or_raises_on_an_overflowing_subscriber():
    """A phone that stopped reading must not be able to wedge the upload path."""
    hub = SightingHub()

    published = MAX_PENDING + 10

    async def scenario():
        async with hub.subscribe() as queue:
            for i in range(published):
                hub.publish(_event(i, 1))
            return queue.qsize(), queue.get_nowait()

    size, first = asyncio.run(scenario())
    # The backlog is dropped in favour of a resync marker: replaying 74 events
    # costs more than the refetch it would be avoiding. Events published after
    # the overflow queue up behind that marker normally — harmless, because the
    # client refetches on seeing it and dedupes the rest by id.
    assert first is RESYNC
    assert size <= MAX_PENDING
    assert size < published


def test_publish_with_no_subscribers_is_a_no_op():
    """The common case: a feeder uploading with nobody watching."""
    SightingHub().publish(_event(1, 1))


# ---------------------------------------------------------------------------
# The stream
# ---------------------------------------------------------------------------
@pytest.fixture
def owner_devices(client, owner_headers):
    return [d["id"] for d in client.get("/devices", headers=owner_headers).json()]


def _drive(user_id, *, last_event_id=None, publish=(), take=1, before_take=None):
    """Open the stream, consume up to `ready`, publish, then take `take` messages."""
    async def scenario():
        gen = events._generate(user_id, last_event_id)
        preamble = []
        try:
            while True:
                msg = await gen.__anext__()
                preamble.append(msg)
                if msg.event == "ready":
                    break

            if before_take is not None:
                before_take()
            for ev in publish:
                sighting_hub.publish(ev)

            out = [await gen.__anext__() for _ in range(take)]
            return preamble, out
        finally:
            await gen.aclose()

    return asyncio.run(scenario())


def test_stream_announces_itself_ready_with_a_retry_hint(client, owner_headers):
    from backend.tests.conftest import IDS

    preamble, _ = _drive(IDS["owner_id"], publish=[_event(9_000_001, 1)])
    ready = preamble[-1]
    assert ready.event == "ready"
    # The browser reconnect interval, so a dropped stream comes back promptly.
    assert ready.retry == 3000


def test_forwards_a_sighting_on_an_accessible_device(client, owner_headers, owner_devices):
    from backend.tests.conftest import IDS

    _, out = _drive(IDS["owner_id"], publish=[_event(9_000_002, owner_devices[0])])

    assert out[0].event == "sighting"
    # The id is what the client resumes from after a dropped connection.
    assert out[0].id == 9_000_002


def test_ignores_a_sighting_on_a_device_the_user_cannot_see(client, owner_devices):
    """Scoping is the whole security surface of the stream."""
    from backend.tests.conftest import IDS

    unreachable = max(owner_devices) + 500
    _, out = _drive(
        IDS["owner_id"],
        publish=[_event(9_000_003, unreachable), _event(9_000_004, owner_devices[0])],
    )

    # The unreachable one is skipped silently; the next accessible one arrives.
    assert out[0].id == 9_000_004


def test_viewer_gets_their_own_devices(client, viewer_headers):
    """A viewer is scoped by the same helper, not excluded from the stream."""
    from backend.tests.conftest import IDS

    visible = [d["id"] for d in client.get("/devices", headers=viewer_headers).json()]
    assert visible, "the fixture viewer should see at least one device"

    _, out = _drive(IDS["viewer_id"], publish=[_event(9_000_005, visible[0])])
    assert out[0].id == 9_000_005


def test_heartbeat_when_idle(client, monkeypatch):
    """An idle stream is indistinguishable from a dead one to a proxy."""
    from backend.tests.conftest import IDS

    monkeypatch.setattr(events, "HEARTBEAT_SECONDS", 0.05)
    _, out = _drive(IDS["owner_id"])

    assert out[0].comment == "keepalive"
    # A heartbeat carries no id — advancing the resume point past an event the
    # client hasn't seen would lose it.
    assert out[0].id is None


def test_overflow_becomes_a_resync(client, owner_devices):
    from backend.tests.conftest import IDS

    flood = [_event(9_100_000 + i, owner_devices[0]) for i in range(MAX_PENDING + 5)]
    _, out = _drive(IDS["owner_id"], publish=flood)

    assert out[0].event == "resync"


# ---------------------------------------------------------------------------
# Last-Event-ID replay
# ---------------------------------------------------------------------------
def test_replays_what_was_missed(client, owner_headers):
    """A dropped connection must not leave a hole in the feed."""
    from backend.tests.conftest import IDS

    # Sorted by id, not taken in list order: /sightings is ordered by datetime,
    # and replay resumes by id — the two disagree whenever a backdated capture
    # has been uploaded from the Pi's offline queue.
    ids = sorted(s["id"] for s in client.get("/sightings?limit=100", headers=owner_headers).json())
    assert len(ids) >= 3
    resume_from = ids[-3]
    expected = ids[-2:]

    preamble, _ = _drive(
        IDS["owner_id"], last_event_id=resume_from,
        publish=[_event(9_000_006, 1)],
    )

    replayed = [m for m in preamble if m.event == "sighting"]
    assert [m.id for m in replayed] == expected  # oldest first
    assert preamble[-1].event == "ready"         # ...then live


def test_replay_is_scoped_to_accessible_devices(client, viewer_headers, owner_headers):
    from backend.tests.conftest import IDS

    visible = {d["id"] for d in client.get("/devices", headers=viewer_headers).json()}
    preamble, _ = _drive(
        IDS["viewer_id"], last_event_id=1, publish=[_event(9_000_007, 1)]
    )

    replayed = [m for m in preamble if m.event == "sighting"]
    assert replayed, "there should be something to replay from id 1"
    for msg in replayed:
        assert json.loads(msg.data)["device_id"] in visible


def test_replay_beyond_the_cap_asks_for_a_full_refetch(client, monkeypatch):
    """200 individual messages cost more than the ~37 KB load they'd replace."""
    from backend.tests.conftest import IDS

    monkeypatch.setattr(events, "MAX_REPLAY", 1)
    preamble, _ = _drive(
        IDS["owner_id"], last_event_id=1, publish=[_event(9_000_008, 1)]
    )

    assert preamble[0].event == "resync"
    assert preamble[0].data == "too_far_behind"


@pytest.mark.parametrize("raw", ["", "abc", "0", "-4", None, "12.5"])
def test_unparseable_last_event_id_is_treated_as_absent(raw):
    """It's a client-supplied header; a bad one must not 500 the stream."""
    assert events._parse_last_event_id(raw) is None


def test_valid_last_event_id_is_parsed():
    assert events._parse_last_event_id("42") == 42


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------
def test_requires_authentication(client):
    assert client.get("/events").status_code == 401


def test_documented_in_the_openapi_schema(client):
    """Unlike /dev, this one *is* part of the frontend contract."""
    paths = client.get("/schema/openapi.json").json()["paths"]
    assert "/events" in paths
