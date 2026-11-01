"""Animal push alerts: one switch, title, tag and throttle per animal group.

The throttle key is (user, feeder, group), apart from the bird throttle. A
squirrel that comes back every few minutes sends one push per half hour, and it
never mutes a bird alert. Animal alerts are push only. They never touch the
feed alert spells.
"""
import asyncio
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.animals.groups import alert_on, alert_title, resolved_alerts
from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import (
    Device,
    FeedSpell,
    PushSubscription,
    Sighting,
    Species,
    User,
    UserPreferences,
)
from backend.notifications import service as notif_module
from backend.notifications.push_sender import PushResult
from backend.notifications.service import NotificationService


async def _station(prefs: dict | None = None) -> dict:
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(name="Alert Owner", email=f"alert_{secrets.token_hex(4)}@test.dev",
                     password_hash="x", role="owner", notify_email=True)
            db.add(u)
            await db.flush()
            d = Device(name="Back Porch", owner_id=u.id, city="Ithaca", state="NY",
                       token=secrets.token_urlsafe(12))
            db.add(d)
            db.add(PushSubscription(
                user_id=u.id, endpoint=f"https://push.example.com/{secrets.token_hex(8)}",
                p256dh="k", auth="a", user_agent="Pytest", created_at=datetime.now(timezone.utc),
            ))
            if prefs is not None:
                db.add(UserPreferences(user_id=u.id, **prefs))
            await db.flush()
            return {"user_id": u.id, "device_id": d.id}


async def _species(kind: str, group: str | None, common: str | None = None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(common_name=common or f"Alert {kind} {secrets.token_hex(3)}",
                         genus="G", species_name=secrets.token_hex(3),
                         kind=kind, animal_group=group)
            db.add(sp)
            await db.flush()
            return sp.id


async def _sighting(species_id: int, device_id: int) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            s = Sighting(species_id=species_id, device_id=device_id,
                         datetime=datetime.now(timezone.utc), confidence_score=0.81,
                         classification_tier_used="gpu", delayed=False)
            db.add(s)
            await db.flush()
            return s.id


def _capture(monkeypatch):
    pushes: list[dict] = []
    emails: list[str] = []

    async def fake_push(target, payload):
        pushes.append(payload)
        return PushResult(ok=True, status=201)

    async def fake_email(*, to_email, **_):
        emails.append(to_email)
        return True

    monkeypatch.setattr(notif_module, "send_push", fake_push)
    monkeypatch.setattr(notif_module, "push_enabled", lambda: True)
    monkeypatch.setattr(notif_module, "send_email", fake_email)
    return pushes, emails


def _visit(svc, species_id, station):
    sid = asyncio.run(_sighting(species_id, station["device_id"]))
    asyncio.run(svc.dispatch(sid, station["device_id"]))
    return sid


# ── Wording and defaults ──────────────────────────────────────────────────────


def test_titles_follow_the_issue():
    assert alert_title("squirrel", "Back Porch") == "Squirrel at Back Porch"
    assert alert_title("bear", "Back Porch") == "Bear at Back Porch. Bring the feeder in tonight."
    assert alert_title("cat", "Back Porch") == "Cat near Back Porch. Birds at risk."
    assert alert_title("deer", "Back Porch") == "Deer at Back Porch"


def test_defaults_are_on_for_squirrel_raccoon_bear_cat_only():
    on = {g for g, v in resolved_alerts(None).items() if v}
    assert on == {"squirrel", "raccoon", "bear", "cat"}
    assert alert_on({"chipmunk": True}, "chipmunk") is True
    assert alert_on({"squirrel": False}, "squirrel") is False
    assert alert_on(None, None) is False


# ── Sending ───────────────────────────────────────────────────────────────────


def test_a_squirrel_sends_one_push_with_its_title_and_tag(client, monkeypatch):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_species("animal", "squirrel", f"Gray Squirrel {secrets.token_hex(2)}"))

    sid = _visit(NotificationService(), squirrel, station)

    [push] = pushes
    assert push["title"] == "Squirrel at Back Porch"
    assert push["tag"] == f"peckdeck-device-{station['device_id']}-animal-squirrel"
    assert push["data"]["sighting_id"] == sid
    assert push["body"].startswith("Gray Squirrel")
    assert emails == [], "animal alerts are push only"


def test_a_second_squirrel_inside_the_interval_is_throttled(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_species("animal", "squirrel"))
    svc = NotificationService()

    _visit(svc, squirrel, station)
    _visit(svc, squirrel, station)

    assert len(pushes) == 1


def test_the_throttle_expires_after_the_users_interval(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station({"animal_quiet_interval_seconds": 60}))
    squirrel = asyncio.run(_species("animal", "squirrel"))
    clock = {"now": 1000.0}
    monkeypatch.setattr(notif_module.time, "monotonic", lambda: clock["now"])
    svc = NotificationService()

    _visit(svc, squirrel, station)
    clock["now"] += 59
    _visit(svc, squirrel, station)
    clock["now"] += 2
    _visit(svc, squirrel, station)

    assert len(pushes) == 2


def test_another_group_has_its_own_throttle(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_species("animal", "squirrel"))
    raccoon = asyncio.run(_species("animal", "raccoon"))
    svc = NotificationService()

    _visit(svc, squirrel, station)
    _visit(svc, raccoon, station)

    assert [p["title"] for p in pushes] == ["Squirrel at Back Porch", "Raccoon at Back Porch"]


def test_a_squirrel_never_mutes_a_bird_or_opens_a_feed_spell(client, monkeypatch):
    pushes, emails = _capture(monkeypatch)
    station = asyncio.run(_station({"quiet_interval_seconds": 600}))
    squirrel = asyncio.run(_species("animal", "squirrel"))
    cardinal = asyncio.run(_species("bird", None))
    svc = NotificationService()

    async def spells() -> int:
        async with get_session_factory()() as db:
            return (await db.execute(
                select(func.count()).select_from(FeedSpell)
                .where(FeedSpell.device_id == station["device_id"])
            )).scalar_one()

    _visit(svc, squirrel, station)
    _visit(svc, cardinal, station)

    assert len(pushes) == 2
    assert pushes[1]["tag"] == f"peckdeck-device-{station['device_id']}"
    assert len(emails) == 1, "the bird alert still goes out by email"
    assert asyncio.run(spells()) == 0
    # And the bird throttle holds for the next bird, not because of the squirrel.
    assert (station["user_id"], station["device_id"]) in svc._last_notified
    assert (station["user_id"], station["device_id"], "squirrel") in svc._last_animal


def test_a_group_off_by_default_sends_nothing_until_switched_on(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    off = asyncio.run(_station())
    on = asyncio.run(_station({"animal_alerts": {"chipmunk": True}}))
    chipmunk = asyncio.run(_species("animal", "chipmunk"))

    _visit(NotificationService(), chipmunk, off)
    assert pushes == []

    _visit(NotificationService(), chipmunk, on)
    assert [p["title"] for p in pushes] == ["Chipmunk at Back Porch"]


def test_a_user_can_switch_a_default_group_off(client, monkeypatch):
    pushes, _ = _capture(monkeypatch)
    station = asyncio.run(_station({"animal_alerts": {"cat": False}}))
    cat = asyncio.run(_species("animal", "cat"))

    _visit(NotificationService(), cat, station)

    assert pushes == []


# ── Preferences API ───────────────────────────────────────────────────────────


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id, 'owner')}"}


def test_preferences_merge_animal_switches(client):
    station = asyncio.run(_station())
    headers = _auth(station["user_id"])

    res = client.put("/users/me/preferences", headers=headers,
                     json={"animal_alerts": {"chipmunk": True, "cat": False},
                           "animal_quiet_interval_seconds": 900})
    assert res.status_code == 200
    res = client.put("/users/me/preferences", headers=headers,
                     json={"animal_alerts": {"deer": True}})

    body = client.get("/users/me/preferences", headers=headers).json()
    assert body["animal_alerts"]["chipmunk"] is True
    assert body["animal_alerts"]["deer"] is True
    assert body["animal_alerts"]["cat"] is False
    assert body["animal_alerts"]["squirrel"] is True
    assert body["animal_quiet_interval_seconds"] == 900


def test_preferences_refuse_an_unknown_group_or_interval(client):
    station = asyncio.run(_station())
    headers = _auth(station["user_id"])

    for body in ({"animal_alerts": {"dragon": True}},
                 {"animal_alerts": {"squirrel": "yes"}},
                 {"animal_quiet_interval_seconds": 5},
                 {"animal_quiet_interval_seconds": 100000}):
        assert client.put("/users/me/preferences", headers=headers, json=body).status_code == 400
