"""The evening digest push and the weekly digest email. See backend/notifications/digest.py.

The issue asks for three cases above all: the day boundary in a non-UTC time
zone, the empty day, and the restart that must not send twice.
"""
import asyncio
import secrets
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from backend.database.connection import get_session_factory
from backend.database.models import Device, PushSubscription, Sighting, User, UserPreferences
from backend.notifications import digest
from backend.notifications.push_sender import PushResult
from backend.species.operations import ANIMAL, get_or_create_species

CHICAGO = "America/Chicago"  # UTC-5 in June
CARDINAL = {"common_name": "Digest Cardinal", "genus": "Cardinalis", "species_name": "cardinalis"}
BLUEBIRD = {"common_name": "Digest Bluebird", "genus": "Sialia", "species_name": "sialis"}
WREN = {"common_name": "Digest Wren", "genus": "Thryothorus", "species_name": "ludovicianus"}
JAY = {"common_name": "Digest Jay", "genus": "Cyanocitta", "species_name": "cristata"}
UNKNOWN = {"common_name": "Unknown", "genus": "Unknown", "species_name": "sp."}
SQUIRREL = {"common_name": "Digest Squirrel", "genus": "Sciurus", "species_name": "carolinensis",
            "kind": ANIMAL, "animal_group": "squirrel"}


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


async def _user(*, push=True, email=False, tz=CHICAGO, push_time="19:00") -> tuple[int, int]:
    """A fresh user with one feeder and one push subscription. Returns (user, device)."""
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(
                name="Digest User", email=f"digest_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="viewer", notify_email=False,
            )
            db.add(user)
            await db.flush()
            db.add(UserPreferences(
                user_id=user.id, time_zone=tz, digest_push=push, digest_email=email,
                digest_push_time=push_time,
            ))
            device = Device(name=f"Digest Feeder {user.id}", owner_id=user.id,
                            token=secrets.token_urlsafe(12))
            db.add(device)
            db.add(PushSubscription(
                user_id=user.id, endpoint=f"https://push.test/{secrets.token_hex(6)}",
                p256dh="k", auth="a", created_at=utc(2026, 1, 1),
            ))
            await db.flush()
            return user.id, device.id


async def _visit(device_id, when, species=CARDINAL, *, tier="gpu", confidence=0.9, image=None):
    async with get_session_factory()() as db:
        async with db.begin():
            sp = await get_or_create_species(db, **species)
            db.add(Sighting(
                species_id=sp.id, device_id=device_id, datetime=when,
                classification_tier_used=tier, confidence_score=confidence, delayed=False,
                image_data=image, thumbnail_data=image and b"thumb-" + image,
            ))


async def _drop_unknown(user_id):
    async with get_session_factory()() as db:
        async with db.begin():
            await db.execute(delete(Sighting).where(
                Sighting.device_id.in_(select(Device.id).where(Device.owner_id == user_id)),
                Sighting.classification_tier_used == "none",
            ))


async def _prefs(user_id) -> UserPreferences:
    async with get_session_factory()() as db:
        return await db.get(UserPreferences, user_id)


@pytest.fixture
def sent(monkeypatch):
    """Fake both senders. Nothing leaves the test."""
    record = {"push": [], "email": []}

    async def fake_push(target, payload):
        record["push"].append((target.endpoint, payload))
        return PushResult(ok=True, status=201)

    async def fake_email(**kwargs):
        record["email"].append(kwargs)
        return True

    monkeypatch.setattr(digest, "send_push", fake_push)
    monkeypatch.setattr(digest, "send_email", fake_email)
    monkeypatch.setattr(digest, "push_enabled", lambda: True)
    return record


def _mine(record, user_id, kind="push"):
    """Only this test's sends. Other tests' users may be due at the same instant."""
    return [o for o in record if o.user_id == user_id and getattr(o, kind)]


# --- The evening push ---

def test_day_boundary_follows_the_users_time_zone(client, sent):
    async def go():
        uid, dev = await _user()
        # 23:30 on 9 June in Chicago. Yesterday, though it is 10 June in UTC.
        await _visit(dev, utc(2026, 6, 10, 4, 30), CARDINAL)
        # 00:30 and 18:30 on 10 June in Chicago.
        await _visit(dev, utc(2026, 6, 10, 5, 30), CARDINAL)
        await _visit(dev, utc(2026, 6, 10, 23, 30), BLUEBIRD)

        # 18:55 local: not yet.
        assert _mine(await digest.run_once(utc(2026, 6, 10, 23, 55)), uid) == []
        # 19:05 local, already 11 June in UTC.
        out = _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)
        return out

    out = asyncio.run(go())
    assert len(out) == 1
    payload = out[0].push
    assert payload["title"] == "Today: 2 birds, 2 species"
    # The cardinal came yesterday, so only the bluebird is new.
    assert payload["body"] == "New for Peck Deck: Digest Bluebird."
    assert payload["data"]["url"] == "/"


def test_empty_day_sends_nothing_and_stays_done(client, sent):
    async def go():
        uid, dev = await _user()
        await _visit(dev, utc(2026, 6, 10, 4, 30), CARDINAL)  # yesterday, local
        await _visit(dev, utc(2026, 6, 10, 15, 0), SQUIRREL)  # today, but not a bird

        first = _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)
        prefs = await _prefs(uid)
        # A bird after the push time does not send a late push.
        await _visit(dev, utc(2026, 6, 11, 1, 0), CARDINAL)
        later = _mine(await digest.run_once(utc(2026, 6, 11, 2, 0)), uid)
        return first, later, prefs

    first, later, prefs = asyncio.run(go())
    assert first == [] and later == []
    assert prefs.digest_push_sent_at is not None


def test_restart_does_not_send_twice(client, sent):
    async def go():
        uid, dev = await _user()
        await _visit(dev, utc(2026, 6, 10, 15, 0), CARDINAL)
        first = _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)
        # A restart keeps nothing in memory. The stored send time is all there is.
        await digest.stop()
        again = _mine(await digest.run_once(utc(2026, 6, 11, 0, 30)), uid)
        # The next evening is a new period.
        await _visit(dev, utc(2026, 6, 11, 15, 0), CARDINAL)
        next_day = _mine(await digest.run_once(utc(2026, 6, 12, 0, 5)), uid)
        return first, again, next_day

    first, again, next_day = asyncio.run(go())
    assert len(first) == 1
    assert again == []
    assert len(next_day) == 1
    assert next_day[0].push["title"] == "Today: 1 bird, 1 species"
    assert next_day[0].push["body"] == "No new species today."


def test_unknown_is_a_bird_not_a_species_and_animals_stay_apart(client, sent):
    async def go():
        uid, dev = await _user()
        await _visit(dev, utc(2026, 6, 10, 15, 0), CARDINAL)
        await _visit(dev, utc(2026, 6, 10, 16, 0), UNKNOWN, tier="none", confidence=0.0)
        await _visit(dev, utc(2026, 6, 10, 17, 0), SQUIRREL)
        await _visit(dev, utc(2026, 6, 10, 17, 30), SQUIRREL)
        return _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)

    out = asyncio.run(go())
    # An old Unknown row would change the retention tests' counts.
    asyncio.run(_drop_unknown(out[0].user_id))
    assert out[0].push["title"] == "Today: 2 birds, 1 species"
    assert out[0].push["body"] == "New for Peck Deck: Digest Cardinal. Also 2 animal visits."


def test_a_low_confidence_lifer_reads_as_new_this_year(client, sent):
    async def go():
        uid, dev = await _user()
        await _visit(dev, utc(2026, 6, 10, 15, 0), WREN, confidence=0.62)
        return _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)

    out = asyncio.run(go())
    assert out[0].push["body"] == "New this year: Digest Wren."


def test_push_off_sends_nothing(client, sent):
    async def go():
        uid, dev = await _user(push=False)
        await _visit(dev, utc(2026, 6, 10, 15, 0), CARDINAL)
        return _mine(await digest.run_once(utc(2026, 6, 11, 0, 5)), uid)

    assert asyncio.run(go()) == []


# --- The weekly email ---

def test_weekly_email_on_sunday_morning_with_the_best_tier2_photos(client, sent):
    async def go():
        uid, dev = await _user(push=False, email=True)
        # The week is 7 to 13 June, Chicago time. Sunday is 14 June.
        await _visit(dev, utc(2026, 6, 7, 4, 0), JAY, image=b"before")  # 6 June local
        await _visit(dev, utc(2026, 6, 8, 15, 0), CARDINAL, confidence=0.81, image=b"card1")
        await _visit(dev, utc(2026, 6, 9, 15, 0), CARDINAL, confidence=0.95, image=b"card2")
        await _visit(dev, utc(2026, 6, 10, 15, 0), BLUEBIRD, confidence=0.90, image=b"blue")
        await _visit(dev, utc(2026, 6, 11, 15, 0), WREN, confidence=0.70, image=b"wren")
        await _visit(dev, utc(2026, 6, 12, 15, 0), JAY, confidence=0.75, image=b"jay")
        # Tier 1 is never "best", however confident.
        await _visit(dev, utc(2026, 6, 12, 16, 0), WREN, tier="local", confidence=0.99, image=b"t1")
        await _visit(dev, utc(2026, 6, 13, 15, 0), SQUIRREL, image=b"sq")

        saturday = _mine(await digest.run_once(utc(2026, 6, 13, 14, 0)), uid, "email")
        too_early = _mine(await digest.run_once(utc(2026, 6, 14, 12, 0)), uid, "email")  # 07:00
        sunday = _mine(await digest.run_once(utc(2026, 6, 14, 13, 30)), uid, "email")  # 08:30
        again = _mine(await digest.run_once(utc(2026, 6, 14, 15, 0)), uid, "email")
        return saturday, too_early, sunday, again

    saturday, too_early, sunday, again = asyncio.run(go())
    assert saturday == [] and too_early == [] and again == []
    assert len(sunday) == 1
    email = sunday[0].email
    assert email["subject"] == "Peck Deck: your week from 7 Jun"
    assert [data for _, data in email["inline_images"]] == [b"thumb-card2", b"thumb-blue", b"thumb-jay"]
    html = email["html_body"]
    assert "6 bird visits, 4 species." in html
    assert "Animal visits: 1" in html
    # The jay came the week before, so it is not new this week.
    assert "Digest Cardinal (first ever)" in html
    assert "Digest Jay (" not in html
    for cid, _ in email["inline_images"]:
        assert f"cid:{cid}" in html


def test_weekly_email_skips_an_empty_week(client, sent):
    async def go():
        uid, dev = await _user(push=False, email=True)
        await _visit(dev, utc(2026, 6, 10, 15, 0), SQUIRREL)
        out = _mine(await digest.run_once(utc(2026, 6, 14, 13, 30)), uid, "email")
        return out, await _prefs(uid)

    out, prefs = asyncio.run(go())
    assert out == []
    assert prefs.digest_email_sent_at is not None


# --- Preferences ---

def test_preferences_default_off_and_validate(client):
    from backend.auth.jwt_utils import create_user_token

    uid, _ = asyncio.run(_user(push=False, tz=None))
    headers = {"Authorization": f"Bearer {create_user_token(uid, 'viewer')}"}

    body = client.get("/users/me/preferences", headers=headers).json()
    assert body["time_zone"] is None
    assert body["digest_push"] is False and body["digest_email"] is False
    assert body["digest_push_time"] == "19:00"

    assert client.put("/users/me/preferences", headers=headers,
                      json={"time_zone": "Mars/Olympus"}).status_code == 400
    assert client.put("/users/me/preferences", headers=headers,
                      json={"digest_push_time": "25:00"}).status_code == 400

    res = client.put("/users/me/preferences", headers=headers, json={
        "time_zone": CHICAGO, "digest_push": True, "digest_push_time": "20:30",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["time_zone"] == CHICAGO
    assert body["digest_push"] is True and body["digest_push_time"] == "20:30"
    assert body["digest_email"] is False
