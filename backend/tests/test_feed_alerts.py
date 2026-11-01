"""Low and out of feed alerts. See backend/feed/monitor.py.

The issue asks for four cases above all: a quiet night that does not fire, a Pi
outage that does not fire, a busy morning that drops to zero and fires, and a
refill that clears the alert.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, DeviceOutage, FeedSpell, Sighting, User
from backend.feed import monitor
from backend.feed.operations import log_refill
from backend.feed.rules import VisitCheck, ago, visit_check, visits_per_fill
from backend.notifications import service
from backend.species.operations import ANIMAL, get_or_create_species
from backend.tests.test_devices import _fresh_owner

NOW = datetime.now(timezone.utc)


# --- The rules on their own ---

def test_e_of_six_fires_on_one_visit_not_two():
    assert VisitCheck(expected=6, observed=1, days=14).dropped
    assert not VisitCheck(expected=6, observed=2, days=14).dropped


def test_quiet_hours_never_fire():
    # E below 6 stays silent, even on zero visits.
    assert not VisitCheck(expected=5.9, observed=0, days=14).dropped


def test_baseline_leaves_out_an_empty_week():
    # 12 visits in the window every day, except a week of empty feed.
    visits = []
    for days_back in range(1, 15):
        if 3 <= days_back <= 9:
            continue
        end = NOW - timedelta(days=days_back)
        visits += [end - timedelta(minutes=10 * i + 5) for i in range(12)]
    visits.sort()
    empty_week = [(NOW - timedelta(days=9, hours=4), NOW - timedelta(days=3) + timedelta(hours=1))]

    check = visit_check(visits, NOW, history_start=NOW - timedelta(days=30), excluded=empty_week)

    assert check.expected == 12
    assert check.days == 7


def test_a_new_feeder_has_no_baseline():
    visits = [NOW - timedelta(days=d, minutes=30) for d in range(1, 4)]
    assert visit_check(visits, NOW, history_start=visits[0], excluded=[]) is None


def test_forecast_needs_three_fills_and_takes_the_median():
    assert visits_per_fill([100, 120]) is None
    # One refill logged late does not drag the forecast up.
    assert visits_per_fill([100, 110, 400]) == 110


def test_ago_reads_plainly():
    assert ago(timedelta(minutes=40)) == "40 min"
    assert ago(timedelta(hours=3, minutes=20)) == "3 h"
    assert ago(timedelta(days=3)) == "3 days"


# --- Against the database ---

async def _feeder(*, last_seen=NOW, trigger_tick=NOW, notify_email=False) -> int:
    """A fresh owner and device, alive now, with no visits."""
    async with get_session_factory()() as db:
        async with db.begin():
            owner = User(
                name="Feed Owner", email=f"feed_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="viewer", notify_email=notify_email,
            )
            db.add(owner)
            await db.flush()
            device = Device(
                name="Feed Test", owner_id=owner.id, token=secrets.token_urlsafe(12),
                feed_type="sunflower", last_seen=last_seen, trigger_tick_at=trigger_tick,
            )
            db.add(device)
            await db.flush()
            return device.id


# Species for _visit. "Unknown" is what the Pi sends when no tier named the bird.
CHICKADEE = {"common_name": "Feed Chickadee", "genus": "Poecile", "species_name": "atricapillus"}
UNKNOWN = {"common_name": "Unknown", "genus": "Unknown", "species_name": "sp."}
SQUIRREL = {"common_name": "Feed Gray Squirrel", "genus": "Sciurus", "species_name": "carolinensis",
            "kind": ANIMAL, "animal_group": "squirrel"}
RACCOON = {"common_name": "Feed Raccoon", "genus": "Procyon", "species_name": "lotor",
           "kind": ANIMAL, "animal_group": "raccoon"}


async def _visit(device_id: int, times: list[datetime], species: dict = CHICKADEE) -> None:
    async with get_session_factory()() as db:
        async with db.begin():
            species = await get_or_create_species(db, **species)
            for t in times:
                db.add(Sighting(
                    species_id=species.id, device_id=device_id, datetime=t,
                    classification_tier_used="gpu", confidence_score=0.9, delayed=False,
                ))


def _busy_mornings(*, today: int = 0) -> list[datetime]:
    """12 visits in the 3 hours before NOW on each of the last 14 days.

    ``today`` visits land in the last 3 hours of today.
    """
    times = []
    for days_back in range(1, 15):
        end = NOW - timedelta(days=days_back)
        times += [end - timedelta(minutes=14 * i + 5) for i in range(12)]
    times += [NOW - timedelta(minutes=14 * i + 5) for i in range(today)]
    return times


async def _check(device_id: int, now: datetime = NOW):
    async with get_session_factory()() as db:
        async with db.begin():
            device = await db.get(Device, device_id)
            return await monitor.check_device(db, device, now)


async def _spells(device_id: int) -> list[tuple[str, bool]]:
    async with get_session_factory()() as db:
        rows = await db.execute(
            select(FeedSpell.state, FeedSpell.ended_at).where(FeedSpell.device_id == device_id)
            .order_by(FeedSpell.id)
        )
        return [(state, ended is None) for state, ended in rows.all()]


async def _owner_headers(device_id: int) -> dict:
    async with get_session_factory()() as db:
        owner_id = (await db.get(Device, device_id)).owner_id
    return {"Authorization": f"Bearer {create_user_token(owner_id, 'viewer')}"}


def _feed(client, device_id: int) -> dict:
    headers = asyncio.run(_owner_headers(device_id))
    device = next(d for d in client.get("/devices", headers=headers).json() if d["id"] == device_id)
    return device["feed"]


def test_busy_morning_that_drops_to_zero_fires_once(client):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))

    alert = asyncio.run(_check(device_id))

    assert alert.state == "out"
    assert alert.title == "Feed may be out at Feed Test"
    assert alert.line == "Feed may be out. Visits stopped about 24 h ago."
    # The next hour's check sends nothing. One alert per empty spell.
    assert asyncio.run(_check(device_id, NOW + timedelta(hours=1))) is None
    assert asyncio.run(_spells(device_id)) == [("out", True)]
    feed = _feed(client, device_id)
    assert feed["state"] == "out"
    assert feed["changed_at"] is not None


def test_normal_morning_does_not_fire(client):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=11)))

    assert asyncio.run(_check(device_id)) is None
    assert _feed(client, device_id)["state"] == "ok"


def test_squirrels_at_an_empty_feeder_do_not_hide_out(client):
    # The birds stopped. A squirrel keeps checking the empty feeder.
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))
    asyncio.run(_visit(device_id, [NOW - timedelta(minutes=14 * i + 5) for i in range(12)], SQUIRREL))

    alert = asyncio.run(_check(device_id))

    assert alert.state == "out"
    # The last bird, not the last squirrel.
    assert alert.line == "Feed may be out. Visits stopped about 24 h ago."
    last = datetime.fromisoformat(_feed(client, device_id)["last_visit_at"])
    assert NOW - last > timedelta(hours=24)


def test_raccoons_at_night_do_not_raise_the_night_baseline(client):
    # Busy birds 12 hours ago. Raccoons every night at this hour, but not tonight.
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, [t - timedelta(hours=12) for t in _busy_mornings()]))
    nights = [t for t in _busy_mornings() if t < NOW - timedelta(hours=3)]
    asyncio.run(_visit(device_id, nights, RACCOON))

    assert asyncio.run(_check(device_id)) is None
    assert asyncio.run(_spells(device_id)) == []


def test_unknown_captures_count_as_bird_visits(client):
    # No tier named today's birds. The camera still saw birds, so the feed is fine.
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))
    asyncio.run(_visit(device_id, [NOW - timedelta(minutes=14 * i + 5) for i in range(11)], UNKNOWN))

    assert asyncio.run(_check(device_id)) is None


def test_quiet_night_does_not_fire(client):
    # Busy every day 12 hours ago, and nothing at this hour on any night.
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, [t - timedelta(hours=12) for t in _busy_mornings()]))

    assert asyncio.run(_check(device_id)) is None
    assert asyncio.run(_spells(device_id)) == []


def test_pi_outage_does_not_fire(client):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))

    async def outage():
        async with get_session_factory()() as db:
            async with db.begin():
                db.add(DeviceOutage(
                    device_id=device_id, started_at=NOW - timedelta(hours=5),
                    ended_at=NOW - timedelta(hours=1),
                ))

    asyncio.run(outage())

    # Back an hour ago. The check waits 3 hours.
    assert asyncio.run(_check(device_id)) is None
    assert asyncio.run(_spells(device_id)) == []


def test_offline_pi_does_not_fire(client):
    device_id = asyncio.run(_feeder(last_seen=NOW - timedelta(hours=2)))
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))

    assert asyncio.run(_check(device_id)) is None


@pytest.mark.parametrize("tick", [None, NOW - timedelta(minutes=11)])
def test_dead_trigger_does_not_fire(client, tick):
    # The Pi heartbeats, but the camera trigger stopped analysing frames.
    device_id = asyncio.run(_feeder(trigger_tick=tick))
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))

    assert asyncio.run(_check(device_id)) is None


def test_refill_clears_the_alert(client):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))
    assert asyncio.run(_check(device_id)).state == "out"
    headers = asyncio.run(_owner_headers(device_id))

    res = client.post(f"/devices/{device_id}/refills", headers=headers)

    assert res.status_code == 201
    feed = res.json()["feed"]
    assert feed["state"] == "ok"
    assert feed["last_refill_at"] is not None
    assert asyncio.run(_spells(device_id)) == [("out", False)]
    # The birds have not found the refill yet. That quiet is not empty feed.
    assert asyncio.run(_check(device_id, NOW + timedelta(minutes=5))) is None


def test_visits_back_to_normal_clear_the_alert(client):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))
    assert asyncio.run(_check(device_id)).state == "out"

    # The owner filled it without tapping Refilled. Birds came back.
    later = NOW + timedelta(days=1)
    asyncio.run(_visit(device_id, [later - timedelta(minutes=14 * i + 5) for i in range(10)]))

    async def alive():
        async with get_session_factory()() as db:
            async with db.begin():
                device = await db.get(Device, device_id)
                device.last_seen = device.trigger_tick_at = later

    asyncio.run(alive())

    assert asyncio.run(_check(device_id, later)) is None
    assert asyncio.run(_spells(device_id)) == [("out", False)]


def test_forecast_warns_low_once_per_fill(client):
    device_id = asyncio.run(_feeder(trigger_tick=None))

    async def fills():
        # Three fills of 10 visits each, then 9 visits since the last refill.
        async with get_session_factory()() as db:
            async with db.begin():
                device = await db.get(Device, device_id)
                for days_back in (40, 30, 20, 10):
                    await log_refill(db, device, device.owner_id, NOW - timedelta(days=days_back))
        times = []
        for start in (40, 30, 20):
            times += [NOW - timedelta(days=start - 1, minutes=i) for i in range(10)]
        times += [NOW - timedelta(days=9, minutes=i) for i in range(9)]
        await _visit(device_id, times)

    asyncio.run(fills())

    alert = asyncio.run(_check(device_id))
    assert alert.state == "low"
    assert alert.line == "Feed may be low. 9 visits since the last refill, and a fill usually lasts about 10."
    assert asyncio.run(_check(device_id, NOW + timedelta(hours=1))) is None
    assert _feed(client, device_id)["state"] == "low"


def test_forecast_counts_birds_only(client):
    device_id = asyncio.run(_feeder(trigger_tick=None))

    async def fills():
        async with get_session_factory()() as db:
            async with db.begin():
                device = await db.get(Device, device_id)
                for days_back in (40, 30, 20, 10):
                    await log_refill(db, device, device.owner_id, NOW - timedelta(days=days_back))
        times = []
        for start in (40, 30, 20):
            times += [NOW - timedelta(days=start - 1, minutes=i) for i in range(10)]
        await _visit(device_id, times)
        # Squirrels since the last refill, and only 2 birds. Far from low.
        await _visit(device_id, [NOW - timedelta(days=9, minutes=i) for i in range(30)], SQUIRREL)
        await _visit(device_id, [NOW - timedelta(days=8, minutes=i) for i in range(2)])

    asyncio.run(fills())

    assert asyncio.run(_check(device_id)) is None


def test_forecast_skips_fills_of_another_feed(client):
    device_id = asyncio.run(_feeder(trigger_tick=None))

    async def fills():
        async with get_session_factory()() as db:
            async with db.begin():
                device = await db.get(Device, device_id)
                for days_back in (40, 30, 20):
                    await log_refill(db, device, device.owner_id, NOW - timedelta(days=days_back))
                device.feed_type = "nyjer"
                await log_refill(db, device, device.owner_id, NOW - timedelta(days=10))
        await _visit(device_id, [NOW - timedelta(days=9, minutes=i) for i in range(50)])

    asyncio.run(fills())

    # Only sunflower fills are on record, so nyjer has no forecast yet.
    assert asyncio.run(_check(device_id)) is None


def test_run_once_sends_the_alert_after_the_commit(client, monkeypatch):
    device_id = asyncio.run(_feeder())
    asyncio.run(_visit(device_id, _busy_mornings(today=0)))
    sent = []

    async def capture(device_id, title, body):
        sent.append((device_id, title))

    monkeypatch.setattr(monitor, "send_feed_alert", capture)

    alerts = asyncio.run(monitor.run_once(NOW))

    assert (device_id, "Feed may be out at Feed Test") in sent
    assert device_id in [a.device_id for a in alerts]


def test_feed_alert_email_goes_to_the_owner(client, monkeypatch):
    device_id = asyncio.run(_feeder(notify_email=True))
    emails = []

    async def capture(**kwargs):
        emails.append(kwargs)
        return True

    monkeypatch.setattr(service, "send_email", capture)

    asyncio.run(service.send_feed_alert(device_id, "Feed may be out at Feed Test", "Feed may be out."))

    assert len(emails) == 1
    assert emails[0]["to_email"].startswith("feed_")
    assert emails[0]["subject"] == "Peck Deck: Feed may be out at Feed Test"


# --- The route and the heartbeat ---

def test_refill_is_owner_only(client, viewer_headers):
    device_id = asyncio.run(_feeder())
    assert client.post(f"/devices/{device_id}/refills", headers=viewer_headers).status_code == 403
    assert client.post(f"/devices/{device_id}/refills").status_code == 401


def test_refill_of_a_missing_feeder_is_404(client, owner_headers):
    assert client.post("/devices/999999/refills", headers=owner_headers).status_code == 404


def test_heartbeat_records_the_trigger_tick(client):
    owner_headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Beat"}, headers=owner_headers).json()
    beat = {"Authorization": f"Bearer {device['token']}"}

    assert client.post("/devices/me/heartbeat", json={"trigger_age_seconds": 2.5},
                       headers=beat).status_code == 200

    async def tick():
        async with get_session_factory()() as db:
            return (await db.get(Device, device["id"])).trigger_tick_at

    first = asyncio.run(tick())
    assert first is not None
    # A beat without it means the trigger is not running.
    client.post("/devices/me/heartbeat", json={}, headers=beat)
    assert asyncio.run(tick()) is None
    assert client.post("/devices/me/heartbeat", json={"trigger_age_seconds": -1},
                       headers=beat).status_code == 400


def test_heartbeat_after_a_gap_logs_an_outage(client):
    owner_headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Gap"}, headers=owner_headers).json()

    async def go_quiet():
        async with get_session_factory()() as db:
            async with db.begin():
                (await db.get(Device, device["id"])).last_seen = NOW - timedelta(hours=2)

    async def outages():
        async with get_session_factory()() as db:
            rows = await db.execute(select(DeviceOutage).where(DeviceOutage.device_id == device["id"]))
            return list(rows.scalars())

    asyncio.run(go_quiet())
    client.post("/devices/me/heartbeat", json={}, headers={"Authorization": f"Bearer {device['token']}"})

    found = asyncio.run(outages())
    assert len(found) == 1
    # Deleting the feeder takes its outages with it.
    assert client.delete(f"/devices/{device['id']}", headers=owner_headers).status_code == 204
    assert asyncio.run(outages()) == []
