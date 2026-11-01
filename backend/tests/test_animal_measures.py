"""Measures on a feeder, their effect on animal visits, and GET /stats/animals.

The effect compares animal visits per camera-up hour in the 14 days before a
measure with the days after. Offline hours come out of both windows, by the
feed alerts' rule: DeviceOutage rows, and the time since last_seen while the
feeder is offline now.
"""
import asyncio
import csv
import math
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.animals import operations as ops
from backend.animals.groups import FEEDER_ANIMALS, GROUPS, ensure_feeder_animals
from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, DeviceOutage, DeviceUser, Sighting, Species, User

NOW = datetime.now(timezone.utc).replace(microsecond=0)
REPO = Path(__file__).resolve().parents[2]


def _auth(user_id: int, role: str = "viewer") -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id, role)}"}


async def _user(role: str = "viewer") -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(name="Measure User", email=f"measure_{secrets.token_hex(4)}@test.dev",
                     password_hash="x", role=role, notify_email=False)
            db.add(u)
            await db.flush()
            return u.id


async def _feeder(owner_id: int, *, last_seen: datetime | None = NOW) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            d = Device(name="Measure Feeder", owner_id=owner_id, token=secrets.token_urlsafe(12),
                       last_seen=last_seen)
            db.add(d)
            await db.flush()
            return d.id


async def _species(kind: str, group: str | None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(common_name=f"M {kind} {secrets.token_hex(3)}", genus="G",
                         species_name=secrets.token_hex(3), kind=kind, animal_group=group)
            db.add(sp)
            await db.flush()
            return sp.id


async def _visits(device_id: int, species_id: int, start: datetime, end: datetime, n: int) -> None:
    """``n`` sightings spread evenly over ``[start, end)``."""
    step = (end - start) / n
    async with get_session_factory()() as db:
        async with db.begin():
            for i in range(n):
                db.add(Sighting(species_id=species_id, device_id=device_id,
                                datetime=start + step * i + step / 2, confidence_score=0.8,
                                classification_tier_used="gpu", delayed=False))


async def _outage(device_id: int, start: datetime, end: datetime) -> None:
    async with get_session_factory()() as db:
        async with db.begin():
            db.add(DeviceOutage(device_id=device_id, started_at=start, ended_at=end))


@pytest.fixture
def owner(client):
    uid = asyncio.run(_user())
    return {"user_id": uid, "device_id": asyncio.run(_feeder(uid)), "headers": _auth(uid)}


def _measures(client, owner):
    return f"/devices/{owner['device_id']}/measures"


# ── Routes ────────────────────────────────────────────────────────────────────


def test_an_owner_adds_ends_and_deletes_a_measure(client, owner):
    url, headers = _measures(client, owner), owner["headers"]
    started = (NOW - timedelta(days=3)).isoformat()

    made = client.post(url, headers=headers,
                       json={"name": "  Baffle on the pole ", "started_at": started, "note": "Cone"})
    assert made.status_code == 201
    m = made.json()
    assert (m["name"], m["note"], m["ended_at"]) == ("Baffle on the pole", "Cone", None)

    ended = client.patch(f"{url}/{m['id']}", headers=headers, json={"ended_at": NOW.isoformat()})
    assert ended.status_code == 200
    assert ended.json()["ended_at"] is not None

    reopened = client.patch(f"{url}/{m['id']}", headers=headers, json={"ended_at": ""})
    assert reopened.json()["ended_at"] is None

    assert [x["id"] for x in client.get(url, headers=headers).json()] == [m["id"]]
    assert client.delete(f"{url}/{m['id']}", headers=headers).status_code == 204
    assert client.get(url, headers=headers).json() == []


def test_a_measure_defaults_to_now(client, owner):
    m = client.post(_measures(client, owner), headers=owner["headers"],
                    json={"name": "Safflower only"}).json()

    assert abs(datetime.fromisoformat(m["started_at"]) - datetime.now(timezone.utc)) < timedelta(minutes=1)


def test_bad_measures_are_refused(client, owner):
    url, headers = _measures(client, owner), owner["headers"]
    future = (NOW + timedelta(days=1)).isoformat()
    for body in ({"name": "  "}, {"name": "x" * 121}, {"name": "Baffle", "started_at": future},
                 {"name": "Baffle", "started_at": "yesterday"}):
        assert client.post(url, headers=headers, json=body).status_code == 400

    m = client.post(url, headers=headers, json={"name": "Baffle"}).json()
    before = (NOW - timedelta(days=2)).isoformat()
    assert client.patch(f"{url}/{m['id']}", headers=headers,
                        json={"ended_at": before}).status_code == 400


def test_a_member_sees_measures_but_cannot_change_them(client, owner):
    member = asyncio.run(_user())

    async def join():
        async with get_session_factory()() as db:
            async with db.begin():
                db.add(DeviceUser(device_id=owner["device_id"], user_id=member))

    asyncio.run(join())
    url = _measures(client, owner)
    m = client.post(url, headers=owner["headers"], json={"name": "Baffle"}).json()

    assert client.get(url, headers=_auth(member)).status_code == 200
    assert client.post(url, headers=_auth(member), json={"name": "Mine"}).status_code == 403
    assert client.patch(f"{url}/{m['id']}", headers=_auth(member), json={"name": "x"}).status_code == 403
    assert client.delete(f"{url}/{m['id']}", headers=_auth(member)).status_code == 403


def test_a_stranger_gets_404(client, owner):
    stranger = _auth(asyncio.run(_user()))
    url = _measures(client, owner)

    assert client.get(url, headers=stranger).status_code == 404
    assert client.post(url, headers=stranger, json={"name": "x"}).status_code == 404


def test_another_feeders_measure_is_404(client, owner):
    other = asyncio.run(_feeder(owner["user_id"]))
    m = client.post(f"/devices/{other}/measures", headers=owner["headers"], json={"name": "x"}).json()

    res = client.patch(f"{_measures(client, owner)}/{m['id']}", headers=owner["headers"],
                       json={"name": "y"})
    assert res.status_code == 404


# ── The maths ─────────────────────────────────────────────────────────────────


def test_rate_ratio_and_its_interval():
    r = ops.rate_ratio(before=100, after=28, before_hours=336, after_hours=336)

    assert r.ratio == pytest.approx(0.28)
    se = math.sqrt(1 / 28 + 1 / 100)
    assert r.low == pytest.approx(0.28 * math.exp(-1.959964 * se))
    assert r.high == pytest.approx(0.28 * math.exp(1.959964 * se))
    assert r.low < 0.28 < r.high


def test_rate_ratio_with_a_zero_count():
    none_after = ops.rate_ratio(before=40, after=0, before_hours=100, after_hours=100)
    none_before = ops.rate_ratio(before=0, after=5, before_hours=100, after_hours=100)

    assert (none_after.ratio, none_after.low, none_after.high) == (0.0, None, None)
    assert (none_before.ratio, none_before.low) == (None, None)


def test_up_hours_leave_out_offline_spans_and_the_time_before_the_first_sighting():
    start = NOW - timedelta(hours=10)
    down = [(start + timedelta(hours=2), start + timedelta(hours=4)),
            (start + timedelta(hours=3), start + timedelta(hours=5))]  # overlapping

    assert ops.up_hours(start, NOW, up_since=start, down=down) == pytest.approx(7)
    assert ops.up_hours(start, NOW, up_since=start + timedelta(hours=6), down=down) == pytest.approx(4)
    assert ops.up_hours(start, NOW, up_since=None, down=[]) == 0


# ── The effect of one measure ─────────────────────────────────────────────────


def test_a_measure_with_an_offline_gap_in_its_window(client, owner):
    """The case the issue names: offline hours come out of the rate.

    100 squirrel visits in the 14 days before. After, the feeder was offline for
    7 of the 14 days and logged 20 visits in the other 7. Per camera-up hour
    that is 20/168 against 100/336, a ratio of 0.4. Counting the dead week as
    up hours would give 0.2 and overstate the measure.
    """
    device = owner["device_id"]
    started = NOW - timedelta(days=14)
    squirrel = asyncio.run(_species("animal", "squirrel"))
    cardinal = asyncio.run(_species("bird", None))
    before_start = started - timedelta(days=14)
    # An older visit, so the feeder was up for the whole before window.
    asyncio.run(_visits(device, cardinal, before_start - timedelta(days=2), before_start - timedelta(days=1), 1))
    asyncio.run(_visits(device, squirrel, before_start, started, 100))
    asyncio.run(_visits(device, cardinal, before_start, started, 200))
    asyncio.run(_outage(device, started, started + timedelta(days=7)))
    asyncio.run(_visits(device, squirrel, started + timedelta(days=7), NOW, 20))
    asyncio.run(_visits(device, cardinal, started + timedelta(days=7), NOW, 100))
    m = client.post(_measures(client, owner), headers=owner["headers"],
                    json={"name": "Baffle on the pole", "started_at": started.isoformat()}).json()

    body = client.get("/stats/animals", headers=owner["headers"],
                      params={"device_id": device, "from_date": (NOW - timedelta(days=40)).date().isoformat()}).json()

    [measure] = body["measures"]
    assert measure["id"] == m["id"]
    effect = measure["effect"]
    assert effect["after_hours"] == pytest.approx(168, abs=0.1)
    assert effect["before_hours"] == pytest.approx(336, abs=0.1)
    assert effect["complete"] is True
    sq = effect["groups"]["squirrel"]
    assert (sq["before"], sq["after"]) == (100, 20)
    assert sq["ratio"] == pytest.approx(0.4, rel=0.01)
    assert sq["low"] < 0.4 < sq["high"]
    # Birds held steady per up hour, so weather or empty feed is not the story.
    assert effect["birds"]["ratio"] == pytest.approx(1.0, rel=0.01)


def test_an_offline_feeder_now_loses_the_hours_since_last_seen(client):
    uid = asyncio.run(_user())
    device = asyncio.run(_feeder(uid, last_seen=NOW - timedelta(days=2)))
    squirrel = asyncio.run(_species("animal", "squirrel"))
    started = NOW - timedelta(days=5)
    asyncio.run(_visits(device, squirrel, started - timedelta(days=14), started, 50))
    client.post(f"/devices/{device}/measures", headers=_auth(uid),
                json={"name": "Moved feeder 3 m from the fence", "started_at": started.isoformat()})

    body = client.get("/stats/animals", headers=_auth(uid), params={"device_id": device}).json()

    effect = body["measures"][0]["effect"]
    assert effect["after_hours"] == pytest.approx(72, abs=0.1)  # 5 days less the 2 offline
    assert effect["complete"] is False


def test_a_measure_ended_early_stops_its_after_window(client, owner):
    started = NOW - timedelta(days=10)
    squirrel = asyncio.run(_species("animal", "squirrel"))
    asyncio.run(_visits(owner["device_id"], squirrel, started - timedelta(days=14), NOW, 60))
    url = _measures(client, owner)
    m = client.post(url, headers=owner["headers"],
                    json={"name": "Hot pepper seed", "started_at": started.isoformat()}).json()
    client.patch(f"{url}/{m['id']}", headers=owner["headers"],
                 json={"ended_at": (started + timedelta(days=3)).isoformat()})

    body = client.get("/stats/animals", headers=owner["headers"],
                      params={"device_id": owner["device_id"]}).json()

    effect = body["measures"][0]["effect"]
    assert effect["after_hours"] == pytest.approx(72, abs=0.1)
    assert effect["complete"] is True


# ── GET /stats/animals ────────────────────────────────────────────────────────


def test_daily_counts_per_group_with_the_bird_count(client, owner):
    device = owner["device_id"]
    squirrel = asyncio.run(_species("animal", "squirrel"))
    raccoon = asyncio.run(_species("animal", "raccoon"))
    cardinal = asyncio.run(_species("bird", None))
    day = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    asyncio.run(_visits(device, squirrel, day, day + timedelta(hours=2), 3))
    asyncio.run(_visits(device, raccoon, day, day + timedelta(hours=1), 1))
    asyncio.run(_visits(device, cardinal, day, day + timedelta(hours=2), 5))

    body = client.get("/stats/animals", headers=owner["headers"], params={
        "device_id": device, "from_date": "2026-10-19", "to_date": "2026-10-21",
    }).json()

    assert [d["date"] for d in body["days"]] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert body["days"][1] == {"date": "2026-10-20", "animals": {"squirrel": 3, "raccoon": 1}, "birds": 5}
    assert body["days"][0]["animals"] == {}
    assert body["groups"] == ["squirrel", "raccoon"]


def test_daily_counts_bucket_by_local_day(client, owner):
    squirrel = asyncio.run(_species("animal", "squirrel"))
    # 02:00 UTC on the 21st is the evening of the 20th in Los Angeles.
    when = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)
    asyncio.run(_visits(owner["device_id"], squirrel, when, when + timedelta(minutes=1), 1))

    body = client.get("/stats/animals", headers=owner["headers"], params={
        "device_id": owner["device_id"], "from_date": "2026-10-20", "to_date": "2026-10-21",
        "tz": "America/Los_Angeles",
    }).json()

    assert [d["animals"] for d in body["days"]] == [{"squirrel": 1}, {}]


def test_stats_animals_refuses_bad_input(client, owner):
    base = {"device_id": owner["device_id"]}
    for extra in ({"tz": "Mars/Base"}, {"from_date": "nope"},
                  {"from_date": "2026-10-10", "to_date": "2026-10-01"},
                  {"from_date": "2024-01-01", "to_date": "2026-01-01"}):
        res = client.get("/stats/animals", headers=owner["headers"], params={**base, **extra})
        assert res.status_code == 400, extra
    stranger = _auth(asyncio.run(_user()))
    assert client.get("/stats/animals", headers=stranger, params=base).status_code == 404


# ── Correcting to an animal before any animal upload ──────────────────────────


def test_a_sighting_can_be_corrected_to_a_squirrel_nobody_has_uploaded(client, owner):
    async def seed_and_bird() -> int:
        async with get_session_factory()() as db:
            async with db.begin():
                await ensure_feeder_animals(db)
        return await _species("bird", None)

    bird = asyncio.run(seed_and_bird())
    asyncio.run(_visits(owner["device_id"], bird, NOW - timedelta(hours=1), NOW, 1))
    headers = owner["headers"]
    species = client.get("/species", headers=headers).json()
    squirrel = next(s for s in species if s["common_name"] == "Eastern Gray Squirrel")
    assert (squirrel["kind"], squirrel["animal_group"]) == ("animal", "squirrel")

    [row] = client.get("/sightings", headers=headers, params={"device_id": owner["device_id"]}).json()
    res = client.patch(f"/sightings/{row['id']}", headers=headers, json={"species_id": squirrel["id"]})

    assert res.status_code == 200
    assert res.json()["species_id"] == squirrel["id"]
    # It left the bird counts.
    counts = client.get("/stats/species-counts", headers=headers).json()
    assert all(c["id"] != squirrel["id"] for c in counts)


def test_seeding_twice_creates_nothing_new(client):
    async def twice() -> int:
        async with get_session_factory()() as db:
            async with db.begin():
                await ensure_feeder_animals(db)
                return await ensure_feeder_animals(db)

    assert asyncio.run(twice()) == 0


def test_the_backend_animal_list_matches_the_csv_and_the_migration():
    with open(REPO / "machine_learning" / "feeder_animals.csv", newline="", encoding="utf-8") as fh:
        rows = [(r["common_name"], r["scientific_name"], r["group"]) for r in csv.DictReader(fh)]
    assert FEEDER_ANIMALS == rows
    assert {g for _, _, g in rows} == set(GROUPS)

    import importlib.util

    path = REPO / "backend/migrations/versions/20261101_1000_animal_measures_and_alerts.py"
    spec = importlib.util.spec_from_file_location("seed_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    seeded = [(c, f"{g} {s}", grp) for c, g, s, grp in migration.FEEDER_ANIMALS]
    assert set(seeded) <= set(rows), "the migration seeds an animal the CSV no longer lists"
