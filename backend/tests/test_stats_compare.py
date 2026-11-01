"""GET /stats/compare, the Compare page's feeders side by side.

A throwaway user sees two feeders: one they own and one they are a member of.
A third feeder belongs to the same other account, and the user is not on it.
Its visits must not show up anywhere. Every feeder and account here is
throwaway, so the exact counts in test_stats.py hold in any test order.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, DeviceUser, Sighting, Species, User

LA = "America/Los_Angeles"


def _species(name: str, kind: str = "bird", group: str | None = None) -> Species:
    return Species(common_name=f"{name} {secrets.token_hex(3)}", genus="Compare",
                   species_name="testus", kind=kind, animal_group=group)


async def _make_houses() -> dict:
    now = datetime.now(timezone.utc)
    # Half an hour before 1 January in Los Angeles. Still this year in UTC.
    la_new_year = datetime(now.astimezone(ZoneInfo(LA)).year, 1, 1, tzinfo=ZoneInfo(LA))
    before_la_new_year = la_new_year.astimezone(timezone.utc) - timedelta(minutes=30)
    last_year = datetime(now.year - 1, 6, 1, tzinfo=timezone.utc)

    async with get_session_factory()() as db:
        async with db.begin():
            user = User(name="Cousin", email=f"compare_{secrets.token_hex(4)}@test.dev",
                        password_hash="x", role="viewer", notify_email=False)
            dad = User(name="Dad", email=f"compare_{secrets.token_hex(4)}@test.dev",
                       password_hash="x", role="viewer", notify_email=False)
            db.add_all([user, dad])
            await db.flush()
            home = Device(name="Home", owner_id=user.id, token=secrets.token_urlsafe(12))
            dads = Device(name="Dad's", owner_id=dad.id, token=secrets.token_urlsafe(12))
            hidden = Device(name="Brother's", owner_id=dad.id,
                            token=secrets.token_urlsafe(12))
            sp = {
                "cardinal": _species("Cardinal"),
                "jay": _species("Jay"),
                "wren": _species("Wren"),
                "owl": _species("Owl"),
                "finch": _species("Hidden Finch"),
                "squirrel": _species("Squirrel", kind="animal", group="squirrel"),
            }
            db.add_all([home, dads, hidden, *sp.values()])
            await db.flush()
            db.add(DeviceUser(device_id=dads.id, user_id=user.id))

            visits = [
                (home, "cardinal", now - timedelta(hours=3)),
                (home, "jay", now - timedelta(hours=2)),
                (home, "cardinal", now - timedelta(hours=1)),
                (home, "cardinal", now - timedelta(hours=1)),
                (home, "cardinal", last_year),
                (home, "owl", before_la_new_year),
                # Five squirrels in one hour would be the busiest hour if
                # animals counted.
                *[(home, "squirrel", now - timedelta(hours=6))] * 5,
                (dads, "cardinal", now - timedelta(hours=5)),
                (dads, "wren", now - timedelta(hours=4)),
                (dads, "wren", now - timedelta(hours=4)),
                # The user cannot see this feeder.
                (hidden, "cardinal", now - timedelta(hours=10)),
                (hidden, "finch", now - timedelta(hours=10)),
            ]
            for dev, name, when in visits:
                db.add(Sighting(species_id=sp[name].id, device_id=dev.id, datetime=when,
                                confidence_score=0.9, classification_tier_used="gpu",
                                delayed=False))
            await db.flush()
            return {
                "now": now, "user_id": user.id,
                "home": home.id, "dads": dads.id, "hidden": hidden.id,
                **{f"{k}_id": v.id for k, v in sp.items()},
            }


@pytest.fixture(scope="module")
def houses(client):
    return asyncio.run(_make_houses())


def _compare(client, houses, **params):
    headers = {"Authorization": f"Bearer {create_user_token(houses['user_id'], 'viewer')}"}
    return client.get("/stats/compare", params=params, headers=headers)


def test_compares_only_the_feeders_the_user_can_see(client, houses):
    body = _compare(client, houses).json()
    assert body["year"] == houses["now"].year
    assert [f["device_id"] for f in body["feeders"]] == [houses["home"], houses["dads"]]
    ids = {s["id"] for s in body["species"]}
    assert houses["finch_id"] not in ids
    for s in body["species"]:
        assert houses["hidden"] not in [f["device_id"] for f in s["firsts"]]


def test_per_feeder_numbers_count_birds_only(client, houses):
    home, dads = _compare(client, houses).json()["feeders"]
    now = houses["now"]
    assert home["name"] == "Home"
    assert home["visits_week"] == 4                 # the squirrels are left out
    assert home["species_year"] == 3                # cardinal, jay, owl in UTC
    assert home["busiest_hour"] == (now - timedelta(hours=1)).hour
    assert dads["visits_week"] == 3
    assert dads["species_year"] == 2
    assert dads["busiest_hour"] == (now - timedelta(hours=4)).hour


def test_first_of_year_per_feeder(client, houses):
    species = _compare(client, houses).json()["species"]
    by_id = {s["id"]: s for s in species}
    assert houses["squirrel_id"] not in by_id

    cardinal = by_id[houses["cardinal_id"]]
    firsts = [(f["device_id"], datetime.fromisoformat(f["first_seen"])) for f in cardinal["firsts"]]
    now = houses["now"]
    # Earliest first. Home's visit last year does not count, nor does the
    # hidden feeder's earlier one.
    assert firsts == [
        (houses["dads"], now - timedelta(hours=5)),
        (houses["home"], now - timedelta(hours=3)),
    ]
    # Seen at only one feeder.
    assert [f["device_id"] for f in by_id[houses["jay_id"]]["firsts"]] == [houses["home"]]
    assert [f["device_id"] for f in by_id[houses["wren_id"]]["firsts"]] == [houses["dads"]]

    # Newest arrival first.
    order = [s["id"] for s in species]
    assert order == [houses["jay_id"], houses["wren_id"], houses["cardinal_id"], houses["owl_id"]]


def test_the_year_starts_in_the_viewers_zone(client, houses):
    body = _compare(client, houses, tz=LA).json()
    assert houses["owl_id"] not in {s["id"] for s in body["species"]}
    assert body["feeders"][0]["species_year"] == 2


def test_unknown_zone_is_400_and_no_token_is_401(client, houses):
    assert _compare(client, houses, tz="Mars/Olympus_Mons").status_code == 400
    assert client.get("/stats/compare").status_code == 401

