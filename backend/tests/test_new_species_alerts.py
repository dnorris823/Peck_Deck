"""New species alerts. See backend/notifications/new_species.py.

A bird sighting is new in one of three ways, and only the strongest counts:
first ever, first at this feeder, first this year. The alert skips the bird
throttle and never starts it. "Unknown" and animals are never new. A sighting
waiting for the Tier 2 re-check decides after it, and a person's correction
sends nothing.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

import backend.sightings.controller as sightings_controller
from backend.auth.jwt_utils import create_user_token
from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, Species
from backend.notifications import new_species
from backend.notifications.service import NotificationService
from backend.sightings import recheck
from backend.sightings.recheck import Answer
from backend.tests.test_animal_alerts import _capture, _station
from backend.tests.test_tier2_recheck import GPU_DOWN, FakeServer, _jpeg

NOW = datetime.now(timezone.utc)
LAST_YEAR = datetime(NOW.year - 1, 6, 1, tzinfo=timezone.utc)


async def _bird(common: str | None = None, kind: str = "bird", group: str | None = None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(
                common_name=common or f"Newbird {secrets.token_hex(3)}",
                genus="G", species_name=secrets.token_hex(3), kind=kind, animal_group=group,
            )
            db.add(sp)
            await db.flush()
            return sp.id


async def _sighting(
    species_id: int, device_id: int, *, when=None, confidence=0.9, tier="gpu",
    pending=False, trace=None,
) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            s = Sighting(
                species_id=species_id, device_id=device_id, datetime=when or NOW,
                confidence_score=confidence, classification_tier_used=tier, delayed=False,
                image_data=_jpeg() if pending else None,
                tier_trace=trace, tier2_recheck="pending" if pending else None,
            )
            db.add(s)
            await db.flush()
            return s.id


async def _second_feeder(user_id: int, name: str = "Front Yard") -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            d = Device(name=name, owner_id=user_id, token=secrets.token_urlsafe(12))
            db.add(d)
            await db.flush()
            return d.id


def _dispatch(svc, sid, device_id, **kw):
    asyncio.run(svc.dispatch(sid, device_id, **kw))


# ── The three kinds ───────────────────────────────────────────────────────────


def test_first_ever(client, monkeypatch):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("Pileated Woodpecker"))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["New for Peck Deck: Pileated Woodpecker at Back Porch"]
    assert pushes[0]["tag"] == f"peckdeck-new-species-{sid}"
    assert pushes[0]["data"]["url"] == f"/?sighting={sid}"
    assert len(emails) == 1, "the new species alert replaces the normal one on email too"


def test_first_at_this_feeder(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    other = asyncio.run(_second_feeder(station["user_id"]))
    bird = asyncio.run(_bird("Tufted Titmouse"))
    asyncio.run(_sighting(bird, other))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["New at Back Porch: Tufted Titmouse"]


def test_first_this_year(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("Dark-eyed Junco"))
    asyncio.run(_sighting(bird, station["device_id"], when=LAST_YEAR))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["First this year: Dark-eyed Junco at Back Porch"]


def test_seen_this_year_is_the_normal_alert(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("House Sparrow"))
    asyncio.run(_sighting(bird, station["device_id"], when=NOW - timedelta(minutes=5)))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["House Sparrow at Back Porch"]
    assert pushes[0]["tag"] == f"peckdeck-device-{station['device_id']}"


def test_only_the_strongest_kind_is_sent(client, monkeypatch):
    """Never recorded is first ever, first at this feeder and first this year
    at once. One push goes, and it says first ever."""
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(asyncio.run(_bird("Brown Creeper")), station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert len(pushes) == 1
    assert pushes[0]["title"].startswith("New for Peck Deck")


def test_a_feeder_the_user_cannot_see_does_not_count(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    stranger = asyncio.run(_station())
    bird = asyncio.run(_bird("Carolina Wren"))
    asyncio.run(_sighting(bird, stranger["device_id"]))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert pushes[0]["title"] == "New for Peck Deck: Carolina Wren at Back Porch"


# ── Switches and the confidence floor ─────────────────────────────────────────


def test_a_kind_switched_off_gets_the_normal_alert(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station({"notify_first_ever": False}))
    sid = asyncio.run(_sighting(asyncio.run(_bird("Hairy Woodpecker")), station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["Hairy Woodpecker at Back Porch"]


def test_first_ever_below_the_floor_gets_the_normal_alert(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(
        asyncio.run(_bird("Cape May Warbler")), station["device_id"], confidence=0.61,
    ))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["Cape May Warbler at Back Porch"]


def test_the_floor_is_for_first_ever_only(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("Fox Sparrow"))
    asyncio.run(_sighting(bird, station["device_id"], when=LAST_YEAR))
    sid = asyncio.run(_sighting(bird, station["device_id"], confidence=0.61))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert pushes[0]["title"] == "First this year: Fox Sparrow at Back Porch"


def test_only_new_species_mutes_the_normal_alert(client, monkeypatch):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station({"notify_new_species_only": True}))
    bird = asyncio.run(_bird("Blue Jay"))
    svc = NotificationService()

    first = asyncio.run(_sighting(bird, station["device_id"]))
    _dispatch(svc, first, station["device_id"])
    again = asyncio.run(_sighting(bird, station["device_id"]))
    _dispatch(svc, again, station["device_id"])

    assert [p["title"] for p in pushes] == ["New for Peck Deck: Blue Jay at Back Porch"]
    assert len(emails) == 1


# ── The bird throttle ─────────────────────────────────────────────────────────


def test_a_new_species_skips_the_throttle(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station({"quiet_interval_seconds": 600}))
    svc = NotificationService()
    known = asyncio.run(_bird("Northern Cardinal"))
    asyncio.run(_sighting(known, station["device_id"], when=NOW - timedelta(minutes=5)))

    _dispatch(svc, asyncio.run(_sighting(known, station["device_id"])), station["device_id"])
    key = (station["user_id"], station["device_id"])
    started = svc._last_notified[key]

    new = asyncio.run(_sighting(asyncio.run(_bird("Evening Grosbeak")), station["device_id"]))
    _dispatch(svc, new, station["device_id"])

    assert [p["title"] for p in pushes] == [
        "Northern Cardinal at Back Porch",
        "New for Peck Deck: Evening Grosbeak at Back Porch",
    ]
    assert svc._last_notified[key] == started, "the new species push must not restart it"


def test_a_new_species_does_not_start_the_throttle(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station({"quiet_interval_seconds": 600}))
    svc = NotificationService()

    new = asyncio.run(_sighting(asyncio.run(_bird("Pine Siskin")), station["device_id"]))
    _dispatch(svc, new, station["device_id"])
    assert (station["user_id"], station["device_id"]) not in svc._last_notified

    known = asyncio.run(_bird("Mourning Dove"))
    asyncio.run(_sighting(known, station["device_id"], when=NOW - timedelta(minutes=5)))
    _dispatch(svc, asyncio.run(_sighting(known, station["device_id"])), station["device_id"])

    assert [p["title"] for p in pushes][-1] == "Mourning Dove at Back Porch"


# ── Animals and Unknown ───────────────────────────────────────────────────────


def test_an_animal_is_never_new(client, monkeypatch):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_bird(f"Squirrel {secrets.token_hex(3)}", kind="animal", group="squirrel"))
    sid = asyncio.run(_sighting(squirrel, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["Squirrel at Back Porch"]
    assert emails == []


def test_unknown_is_never_new(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    unknown = asyncio.run(_bird("Unknown"))
    sid = asyncio.run(_sighting(unknown, station["device_id"], tier="none", confidence=0.0))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["Unknown at Back Porch"]


# ── The Tier 2 re-check ───────────────────────────────────────────────────────


@pytest.fixture
def recheck_on(monkeypatch):
    monkeypatch.setattr(settings, "TIER2_RECHECK_INTERVAL_SECONDS", 60)


def test_a_pending_sighting_waits_for_the_recheck(client, monkeypatch, recheck_on):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(
        asyncio.run(_bird("Pi Guess")), station["device_id"],
        tier="local", pending=True, trace=GPU_DOWN,
    ))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert [p["title"] for p in pushes] == ["Pi Guess at Back Porch"]


def test_with_the_recheck_off_a_pending_sighting_decides_now(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(
        asyncio.run(_bird("Pi Only")), station["device_id"],
        tier="local", pending=True, trace=GPU_DOWN,
    ))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert pushes[0]["title"] == "New for Peck Deck: Pi Only at Back Porch"


def test_a_pending_sighting_is_not_a_record(client, monkeypatch, recheck_on):
    """A Tier 1 fallback and a later Tier 2 answer of the same species must not
    hide each other. The Tier 2 one is first ever until the re-check confirms
    the Tier 1 one."""
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("Red-breasted Nuthatch"))
    asyncio.run(_sighting(bird, station["device_id"], tier="local", pending=True, trace=GPU_DOWN))
    sid = asyncio.run(_sighting(bird, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"])

    assert pushes[0]["title"].startswith("New for Peck Deck: Red-breasted Nuthatch")


class _Recorder:
    def __init__(self):
        self.calls = []

    async def dispatch(self, sighting_id, device_id, **kw):
        self.calls.append((sighting_id, device_id, kw))


def _recheck(monkeypatch, sid, answer):
    recorder = _Recorder()
    monkeypatch.setattr(recheck, "notification_service", recorder)
    monkeypatch.setattr(recheck.sighting_hub, "publish", lambda _e: None)
    monkeypatch.setattr(recheck, "enrich_if_sparse", lambda _s: None)

    async def run():
        outcome = await recheck.recheck_one(sid, FakeServer(answer))
        await asyncio.sleep(0)  # let the fire-and-forget task run
        return outcome

    return asyncio.run(run()), recorder.calls


def test_the_recheck_sends_the_push_for_a_new_species(client, monkeypatch, recheck_on):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    tier1 = asyncio.run(_bird("Song Sparrow"))
    # Tier 1's guess is a species the user has seen, so the upload is not new.
    asyncio.run(_sighting(tier1, station["device_id"], when=NOW - timedelta(minutes=5)))
    sid = asyncio.run(_sighting(
        tier1, station["device_id"], tier="local", pending=True, trace=GPU_DOWN,
    ))
    name = f"Lincoln's Sparrow {secrets.token_hex(3)}"

    outcome, calls = _recheck(monkeypatch, sid, Answer(name, "Melospiza lincolnii", 0.92))

    assert outcome == "replaced"
    assert calls == [(sid, station["device_id"], {"after_recheck": True})]
    _dispatch(NotificationService(), sid, station["device_id"], after_recheck=True)
    assert [p["title"] for p in pushes] == [f"New for Peck Deck: {name} at Back Porch"]


def test_the_recheck_sends_nothing_for_a_known_species(client, monkeypatch, recheck_on):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station())
    bird = asyncio.run(_bird("American Goldfinch"))
    asyncio.run(_sighting(bird, station["device_id"], when=NOW - timedelta(minutes=5)))
    sid = asyncio.run(_sighting(bird, station["device_id"], tier="local", pending=True,
                                trace=GPU_DOWN))
    asyncio.run(recheck._apply(sid, None, outcome="rejected"))

    _dispatch(NotificationService(), sid, station["device_id"], after_recheck=True)

    assert pushes == [] and emails == [], "the upload already sent the normal alert"


def test_the_recheck_sends_no_animal_push(client, monkeypatch, recheck_on):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_bird(f"Squirrel {secrets.token_hex(3)}", kind="animal", group="squirrel"))
    sid = asyncio.run(_sighting(squirrel, station["device_id"]))

    _dispatch(NotificationService(), sid, station["device_id"], after_recheck=True)

    assert pushes == []


def test_a_correction_during_the_recheck_sends_nothing(client, monkeypatch, recheck_on):
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(asyncio.run(_bird("Corrected Bird")), station["device_id"],
                                tier="local", pending=True, trace=GPU_DOWN))

    async def correct():
        async with get_session_factory()() as db:
            async with db.begin():
                s = await db.get(Sighting, sid)
                s.corrected_at = NOW
                s.original_species_id = s.species_id

    asyncio.run(correct())
    outcome, calls = _recheck(monkeypatch, sid, Answer("Whatever", "", 0.95))

    assert outcome == "corrected"
    assert calls == []


# ── A person's correction ─────────────────────────────────────────────────────


def test_a_correction_never_sends_a_push(client, monkeypatch):
    station = asyncio.run(_station())
    sid = asyncio.run(_sighting(asyncio.run(_bird("Misnamed Bird")), station["device_id"]))
    target = asyncio.run(_bird("Bohemian Waxwing"))
    sent = []

    async def record(*a, **k):
        sent.append(a)

    import backend.sightings.aftercare as aftercare
    monkeypatch.setattr(aftercare.notification_service, "dispatch", record)
    monkeypatch.setattr(sightings_controller.sighting_hub, "publish", lambda _e: None)
    headers = {"Authorization": f"Bearer {create_user_token(station['user_id'], 'owner')}"}

    res = client.patch(f"/sightings/{sid}", json={"species_id": target}, headers=headers)

    assert res.status_code == 200
    assert sent == []


def test_wanted_needs_the_switch_and_the_floor():
    assert new_species.wanted(None, None, 0.99) is False
    assert new_species.wanted(new_species.FIRST_EVER, None, 0.70) is True
    assert new_species.wanted(new_species.FIRST_EVER, None, 0.69) is False
    assert new_species.wanted(new_species.FIRST_THIS_YEAR, None, 0.10) is True
