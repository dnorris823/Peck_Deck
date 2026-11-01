"""The Tier 2 re-check of Tier 1 fallbacks. See backend/sightings/recheck.py.

The upload marks a sighting pending when the Pi's trace shows Tier 2 gave no
answer. A pass then asks the inference server about each pending row, oldest
first. These tests drive single passes with a fake server, and the real HTTP
client against a small aiohttp server on localhost.
"""
import asyncio
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web
from PIL import Image
from sqlalchemy import select, update

import backend.sightings.aftercare as sighting_aftercare
from backend import retention
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, Species
from backend.events.hub import SightingUpdated
from backend.sightings import recheck
from backend.sightings.recheck import (
    AnimalAnswer,
    Answer,
    ImageRejected,
    InferenceClient,
    ServerDown,
)
from backend.species.operations import get_or_create_species
from backend.tests.test_sightings_upload import _fresh_device_token, _silence_side_effects

NOW = datetime.now(timezone.utc)


def _jpeg(width=640, height=480) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (90, 120, 60)).save(out, "JPEG")
    return out.getvalue()


def _trace(*entries):
    """TierAttempt dicts from ``(tier, outcome, confidence)`` tuples."""
    bars = recheck.DEFAULT_THRESHOLDS
    return [
        {"tier": t, "outcome": o, "confidence": c, "threshold": bars[t]}
        for t, o, c in entries
    ]


GPU_DOWN = _trace(("gpu", "failed", None), ("local", "accepted", 0.9))


class FakeServer:
    """Stands in for InferenceClient. Answers are handed out in order."""

    def __init__(self, *answers, up=True):
        self.answers = list(answers)
        self.up = up
        self.images: list[bytes] = []

    async def healthy(self) -> bool:
        return self.up

    async def classify(self, image: bytes) -> Answer:
        self.images.append(image)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def published(monkeypatch):
    """Record what the re-check publishes, instead of fanning it out."""
    events = []

    class _Hub:
        def publish(self, event):
            events.append(event)

    monkeypatch.setattr(recheck, "sighting_hub", _Hub())
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _async_noop)
    monkeypatch.setattr(recheck, "notification_service", _NoAlerts())
    return events


class _NoAlerts:
    """Stands in for the notification service. The new species alert after a
    re-check has its own tests, in test_new_species_alerts.py."""

    async def dispatch(self, *_a, **_k):
        return None


async def _async_noop(*_a, **_k):
    return None


async def _device_id() -> int:
    token = await _fresh_device_token()
    async with get_session_factory()() as db:
        return (await db.execute(select(Device.id).where(Device.token == token))).scalar_one()


async def _add(
    *,
    common_name="Pi Sparrow",
    tier="local",
    confidence=0.9,
    trace=GPU_DOWN,
    pending=True,
    image=None,
    crop_box=None,
    age_minutes=0,
    corrected=False,
    device_id=None,
) -> int:
    device_id = device_id or await _device_id()
    async with get_session_factory()() as db:
        async with db.begin():
            species = await get_or_create_species(
                db, common_name=common_name, genus=common_name.split()[0], species_name="sp."
            )
            s = Sighting(
                species_id=species.id,
                device_id=device_id,
                datetime=NOW - timedelta(minutes=age_minutes),
                image_data=_jpeg() if image is None else image,
                classification_tier_used=tier,
                confidence_score=confidence,
                delayed=False,
                tier_trace=trace,
                tier2_recheck="pending" if pending else None,
                crop_box=crop_box,
            )
            if corrected:
                s.original_species_id = species.id
                s.corrected_at = NOW
            db.add(s)
            await db.flush()
            return s.id


async def _row(sighting_id: int) -> tuple[Sighting, str]:
    async with get_session_factory()() as db:
        s = (
            await db.execute(
                select(Sighting).where(Sighting.id == sighting_id)
            )
        ).scalar_one()
        name = (await db.get(Species, s.species_id)).common_name
        return s, name


async def _species_name(species_id: int) -> str:
    async with get_session_factory()() as db:
        return (await db.get(Species, species_id)).common_name


async def _clear_pending() -> None:
    """Mark every pending row done, so a pass sees only this test's rows."""
    async with get_session_factory()() as db:
        async with db.begin():
            await db.execute(
                update(Sighting)
                .where(Sighting.tier2_recheck == "pending")
                .values(tier2_recheck="done")
            )


# ── Which sightings wait ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("trace", "tier", "expected"),
    [
        (_trace(("gpu", "failed", None), ("local", "accepted", 0.9)), "local", True),
        (_trace(("gpu", "failed", None), ("local", "failed", None)), "none", True),
        (_trace(("gpu", "not_run", None), ("local", "not_run", None)), "none", True),
        (_trace(("gpu", "accepted", 0.8), ("local", "not_run", None)), "gpu", False),
        (_trace(("gpu", "below_threshold", 0.3), ("local", "accepted", 0.9)), "local", False),
        (_trace(("local", "accepted", 0.9)), "local", False),
        (_trace(("local", "accepted", 0.9), ("gpu", "not_run", None)), "local", False),
        (None, "local", False),
        ([], "local", False),
    ],
    ids=[
        "gpu-failed", "every-tier-failed", "queue-overflow", "gpu-accepted",
        "gpu-below-threshold", "no-gpu-entry", "auto-local-accepted", "no-trace",
        "empty-trace",
    ],
)
def test_needs_recheck(trace, tier, expected):
    assert recheck.needs_recheck(trace, tier) is expected


def _upload(client, token, *, trace, tier="local", crop_box=None, image=None):
    data = {
        "timestamp": "2026-10-31T10:30:00",
        "common_name": "Upload Finch",
        "scientific_name": "Haemorhous testus",
        "confidence_score": "0.9",
        "classification_tier_used": tier,
    }
    if trace is not None:
        data["tier_trace"] = json.dumps(trace)
    if crop_box is not None:
        data["crop_box"] = crop_box
    return client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        files={"image": ("bird.jpg", image or _jpeg(), "image/jpeg")},
    )


def test_upload_with_gpu_failed_is_pending(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, trace=GPU_DOWN, crop_box="[10, 20, 110, 120]")

    assert res.status_code == 201
    body = res.json()
    assert body["tier2_recheck"] == "pending"
    assert body["provisional_species_id"] is None
    assert body["rechecked_at"] is None
    s, _ = asyncio.run(_row(body["id"]))
    assert s.crop_box == [10, 20, 110, 120]


def test_upload_with_gpu_answer_is_not_pending(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    trace = _trace(("gpu", "accepted", 0.8), ("local", "not_run", None))
    res = _upload(client, token, trace=trace, tier="gpu")

    assert res.status_code == 201
    assert res.json()["tier2_recheck"] is None


def test_upload_without_trace_is_not_pending(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, trace=None)

    assert res.status_code == 201
    assert res.json()["tier2_recheck"] is None


@pytest.mark.parametrize(
    "raw", ["not json", "[1, 2, 3]", "[10, 20, 5, 120]", "[-1, 0, 10, 10]", "[1.5, 0, 10, 10]"]
)
def test_upload_with_a_bad_crop_box_keeps_the_sighting(client, monkeypatch, raw):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, trace=GPU_DOWN, crop_box=raw)

    assert res.status_code == 201
    s, _ = asyncio.run(_row(res.json()["id"]))
    assert s.crop_box is None
    assert s.tier2_recheck == "pending"


# ── What a re-check does ──────────────────────────────────────────────────────


def test_confident_tier2_replaces_the_species(client, published):
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.9))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.82))

    outcome = asyncio.run(recheck.recheck_one(sid, server))

    assert outcome == "replaced"
    s, name = asyncio.run(_row(sid))
    assert name == "House Finch"
    assert asyncio.run(_species_name(s.provisional_species_id)) == "Pi Sparrow"
    assert s.classification_tier_used == "gpu"
    assert s.confidence_score == pytest.approx(0.82)
    assert s.tier2_recheck == "done"
    assert s.rechecked_at is not None
    # The Pi's own record of the outage stays.
    assert s.tier_trace == GPU_DOWN

    [event] = published
    assert isinstance(event, SightingUpdated)
    assert event.sighting_id == sid
    assert event.payload["species_id"] == s.species_id
    assert event.payload["provisional_species_id"] == s.provisional_species_id
    assert event.payload["tier2_recheck"] == "done"


def test_weak_tier2_keeps_a_confident_tier1(client, published):
    # Tier 1 at 0.95 is 112% of its 0.85 bar. Tier 2 at 0.40 is 67% of 0.60.
    sid = asyncio.run(_add(confidence=0.95))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.40))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "kept"

    s, name = asyncio.run(_row(sid))
    assert name == "Pi Sparrow"
    assert s.classification_tier_used == "local"
    assert s.provisional_species_id is None
    assert s.tier2_recheck == "done"
    assert len(published) == 1


def test_weak_tier2_beats_a_weaker_tier1(client, published):
    # Both below their bars. Tier 1 at 0.50 is 59% of 0.85, Tier 2 at 0.50 is 83%.
    trace = _trace(("gpu", "failed", None), ("local", "below_threshold", 0.5))
    sid = asyncio.run(_add(confidence=0.5, trace=trace))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.50))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"


def test_tier2_threshold_comes_from_the_trace(client, published):
    # The Pi held Tier 2 to 0.30, so 0.35 meets it even against a sure Tier 1.
    trace = [
        {"tier": "gpu", "outcome": "failed", "confidence": None, "threshold": 0.30},
        {"tier": "local", "outcome": "accepted", "confidence": 0.99, "threshold": 0.85},
    ]
    sid = asyncio.run(_add(confidence=0.99, trace=trace))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.35))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"


def test_unknown_takes_any_tier2_answer(client, published):
    trace = _trace(("gpu", "not_run", None), ("local", "not_run", None))
    sid = asyncio.run(_add(common_name="Unknown", tier="none", confidence=0.0, trace=trace))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.05))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"

    s, name = asyncio.run(_row(sid))
    assert name == "House Finch"
    assert asyncio.run(_species_name(s.provisional_species_id)) == "Unknown"


def test_unknown_from_tier2_never_replaces(client, published):
    sid = asyncio.run(_add(confidence=0.3))
    server = FakeServer(Answer("Unknown", "", 0.99))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "kept"
    assert asyncio.run(_row(sid))[1] == "Pi Sparrow"


def test_a_corrected_sighting_keeps_the_persons_species(client, published):
    sid = asyncio.run(_add(common_name="Person Wren", corrected=True))
    server = FakeServer()

    assert asyncio.run(recheck.recheck_one(sid, server)) == "corrected"

    s, name = asyncio.run(_row(sid))
    assert name == "Person Wren"
    assert s.tier2_recheck == "done"
    assert s.provisional_species_id is None
    # It never went to the server.
    assert server.images == []


def test_the_crop_box_is_what_goes_to_the_server(client, published):
    sid = asyncio.run(_add(image=_jpeg(640, 480), crop_box=[100, 50, 300, 250]))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.9))

    asyncio.run(recheck.recheck_one(sid, server))

    with Image.open(io.BytesIO(server.images[0])) as sent:
        assert sent.size == (200, 200)


def test_a_box_outside_the_image_sends_the_full_frame():
    image = _jpeg(640, 480)
    assert recheck.crop_image(image, [600, 400, 900, 700]) == image
    assert recheck.crop_image(image, None) == image
    assert recheck.crop_image(b"not a jpeg", [0, 0, 10, 10]) == b"not a jpeg"


# ── A pass ────────────────────────────────────────────────────────────────────


def test_a_pass_runs_oldest_first(client, published):
    asyncio.run(_clear_pending())
    device_id = asyncio.run(_device_id())
    newer = asyncio.run(_add(age_minutes=5, device_id=device_id))
    older = asyncio.run(_add(age_minutes=50, device_id=device_id))
    server = FakeServer(
        Answer("Older Finch", "Haemorhous olderus", 0.9),
        Answer("Newer Finch", "Haemorhous newerus", 0.9),
    )

    assert asyncio.run(recheck.run_pass(server)) == 2

    assert asyncio.run(_row(older))[1] == "Older Finch"
    assert asyncio.run(_row(newer))[1] == "Newer Finch"


def test_a_pass_waits_while_the_server_is_down(client, published):
    asyncio.run(_clear_pending())
    sid = asyncio.run(_add())
    server = FakeServer(up=False)

    assert asyncio.run(recheck.run_pass(server)) == 0

    assert asyncio.run(_row(sid))[0].tier2_recheck == "pending"
    assert server.images == []
    assert published == []


def test_the_server_dropping_mid_pass_leaves_the_rest_pending(client, published):
    asyncio.run(_clear_pending())
    device_id = asyncio.run(_device_id())
    first, second, third = (
        asyncio.run(_add(age_minutes=age, device_id=device_id)) for age in (30, 20, 10)
    )
    server = FakeServer(
        Answer("House Finch", "Haemorhous mexicanus", 0.9),
        ServerDown("connection refused"),
    )

    assert asyncio.run(recheck.run_pass(server)) == 1

    assert asyncio.run(_row(first))[0].tier2_recheck == "done"
    assert asyncio.run(_row(second))[0].tier2_recheck == "pending"
    assert asyncio.run(_row(third))[0].tier2_recheck == "pending"
    # The third was never sent.
    assert len(server.images) == 2


def test_a_4xx_marks_one_row_done_and_the_pass_goes_on(client, published):
    asyncio.run(_clear_pending())
    device_id = asyncio.run(_device_id())
    bad = asyncio.run(_add(age_minutes=20, device_id=device_id))
    good = asyncio.run(_add(age_minutes=10, device_id=device_id))
    server = FakeServer(
        ImageRejected("HTTP 400"),
        Answer("House Finch", "Haemorhous mexicanus", 0.9),
    )

    assert asyncio.run(recheck.run_pass(server)) == 2

    s, name = asyncio.run(_row(bad))
    assert s.tier2_recheck == "done"
    assert name == "Pi Sparrow"
    assert s.provisional_species_id is None
    assert asyncio.run(_row(good))[1] == "House Finch"


def test_retention_skips_a_pending_unknown(client):
    trace = _trace(("gpu", "failed", None), ("local", "failed", None))
    old_pending = asyncio.run(
        _add(common_name="Unknown", tier="none", confidence=0.0, trace=trace,
             age_minutes=60 * 24 * 40)
    )

    async def _apply():
        async with get_session_factory()() as db:
            async with db.begin():
                await retention.delete_old_unknown(db, 30)

    asyncio.run(_apply())

    assert asyncio.run(_row(old_pending))[0].tier2_recheck == "pending"
    asyncio.run(_clear_pending())


# ── The HTTP client ───────────────────────────────────────────────────────────


async def _with_server(routes, check):
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        return await check(InferenceClient(f"http://127.0.0.1:{port}"))
    finally:
        await runner.cleanup()


def _status_route(status, body=None):
    async def handler(request):
        await request.read()
        return web.json_response(body or {"detail": "x"}, status=status)

    return handler


def test_client_reads_an_answer():
    routes = [web.post("/classify", _status_route(
        200, {"common_name": "House Finch", "scientific_name": "Haemorhous mexicanus",
              "confidence": 0.7}))]

    answer = asyncio.run(_with_server(routes, lambda c: c.classify(b"jpeg")))

    assert answer == Answer("House Finch", "Haemorhous mexicanus", 0.7)


@pytest.mark.parametrize(("status", "error"), [(400, ImageRejected), (413, ImageRejected),
                                               (503, ServerDown), (500, ServerDown)])
def test_client_sorts_status_codes(status, error):
    routes = [web.post("/classify", _status_route(status))]

    with pytest.raises(error):
        asyncio.run(_with_server(routes, lambda c: c.classify(b"jpeg")))


def test_client_treats_a_closed_port_as_down():
    client = InferenceClient("http://127.0.0.1:9")

    assert asyncio.run(client.healthy()) is False
    with pytest.raises(ServerDown):
        asyncio.run(client.classify(b"jpeg"))


def test_client_health_needs_the_model_loaded():
    loading = [web.get("/health", _status_route(200, {"status": "ok", "model_ready": False}))]
    ready = [web.get("/health", _status_route(200, {"status": "ok", "model_ready": True}))]

    assert asyncio.run(_with_server(loading, lambda c: c.healthy())) is False
    assert asyncio.run(_with_server(ready, lambda c: c.healthy())) is True


# ── Feeder animals ────────────────────────────────────────────────────────────
# The Pi's rule: the animal wins when it meets TIER2_ANIMAL_THRESHOLD and beats
# Tier 2's bird. A squirrel caught while the 5080 was off has a Tier 1 bird.

SQUIRREL = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.81)


async def _species(species_id: int) -> Species:
    async with get_session_factory()() as db:
        return await db.get(Species, species_id)


def test_a_tier1_bird_becomes_a_squirrel(client, published):
    # Tier 1 at 0.95 clears its bar. It still loses, because it knows birds only.
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.95))
    server = FakeServer(Answer("Blue Jay", "Cyanocitta cristata", 0.03, animal=SQUIRREL))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"

    s, name = asyncio.run(_row(sid))
    assert name == "Eastern Gray Squirrel"
    species = asyncio.run(_species(s.species_id))
    assert (species.kind, species.animal_group) == ("animal", "squirrel")
    assert asyncio.run(_species_name(s.provisional_species_id)) == "Pi Sparrow"
    assert s.classification_tier_used == "gpu"
    assert s.confidence_score == pytest.approx(0.81)
    assert s.tier2_recheck == "done"
    assert s.tier_trace == GPU_DOWN
    [event] = published
    assert event.payload["species_id"] == s.species_id


def test_an_unknown_becomes_a_squirrel(client, published):
    trace = _trace(("gpu", "not_run", None), ("local", "not_run", None))
    sid = asyncio.run(_add(common_name="Unknown", tier="none", confidence=0.0, trace=trace))
    server = FakeServer(Answer("Blue Jay", "Cyanocitta cristata", 0.03, animal=SQUIRREL))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"
    assert asyncio.run(_row(sid))[1] == "Eastern Gray Squirrel"


def test_a_bird_stays_a_bird_when_the_animal_score_is_low(client, published):
    weak = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.04)
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.9))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.82, animal=weak))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"

    s, name = asyncio.run(_row(sid))
    assert name == "House Finch"
    assert asyncio.run(_species(s.species_id)).kind == "bird"
    assert s.confidence_score == pytest.approx(0.82)


def test_an_animal_below_the_bar_leaves_the_bird_rule_to_decide(client, published):
    # The animal beats Tier 2's bird but misses 0.30. Tier 1 at 0.95 then stands.
    weak = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.25)
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.95))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.05, animal=weak))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "kept"
    assert asyncio.run(_row(sid))[1] == "Pi Sparrow"


def test_an_animal_that_does_not_beat_the_bird_loses(client, published):
    close = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.70)
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.9))
    server = FakeServer(Answer("House Finch", "Haemorhous mexicanus", 0.75, animal=close))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "replaced"
    assert asyncio.run(_row(sid))[1] == "House Finch"


def test_the_animal_bar_comes_from_the_setting(client, published, monkeypatch):
    monkeypatch.setattr(recheck.settings, "TIER2_ANIMAL_THRESHOLD", 0.9)
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.95))
    server = FakeServer(Answer("Blue Jay", "Cyanocitta cristata", 0.03, animal=SQUIRREL))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "kept"
    assert asyncio.run(_row(sid))[1] == "Pi Sparrow"


def test_the_default_animal_bar_matches_the_pi():
    from raspberry_pi_code.config import DEFAULT_TIER2_ANIMAL_THRESHOLD

    assert recheck.settings.TIER2_ANIMAL_THRESHOLD == DEFAULT_TIER2_ANIMAL_THRESHOLD


def test_a_correction_during_the_call_beats_a_squirrel(client, published):
    sid = asyncio.run(_add(common_name="Pi Sparrow", confidence=0.95))

    class CorrectedMidCall(FakeServer):
        async def classify(self, image):
            async with get_session_factory()() as db:
                async with db.begin():
                    await db.execute(
                        update(Sighting).where(Sighting.id == sid).values(corrected_at=NOW)
                    )
            return await super().classify(image)

    server = CorrectedMidCall(Answer("Blue Jay", "Cyanocitta cristata", 0.03, animal=SQUIRREL))

    assert asyncio.run(recheck.recheck_one(sid, server)) == "corrected"
    s, name = asyncio.run(_row(sid))
    assert name == "Pi Sparrow"
    assert s.provisional_species_id is None


def test_client_reads_the_animal_field():
    routes = [web.post("/classify", _status_route(200, {
        "common_name": "Blue Jay", "scientific_name": "Cyanocitta cristata", "confidence": 0.03,
        "animal": {"common_name": "Eastern Gray Squirrel", "scientific_name": "Sciurus carolinensis",
                   "group": "squirrel", "confidence": 0.81},
    }))]

    answer = asyncio.run(_with_server(routes, lambda c: c.classify(b"jpeg")))

    assert answer.confidence == 0.03
    assert answer.animal == SQUIRREL


@pytest.mark.parametrize("animal", [None, {"group": "squirrel"}, "squirrel"])
def test_client_keeps_the_bird_without_a_readable_animal(animal):
    routes = [web.post("/classify", _status_route(200, {
        "common_name": "House Finch", "scientific_name": "Haemorhous mexicanus",
        "confidence": 0.7, "animal": animal,
    }))]

    answer = asyncio.run(_with_server(routes, lambda c: c.classify(b"jpeg")))

    assert answer == Answer("House Finch", "Haemorhous mexicanus", 0.7)
