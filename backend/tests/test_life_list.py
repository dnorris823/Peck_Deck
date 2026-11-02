"""GET /stats/life-list: the life list and the year list.

The visits sit on a throwaway user's two feeders, so nothing else in the suite
sees them. Times are Los Angeles wall-clock times, so the local year bounds can
be asserted exactly. One cardinal visit is 20:00 on 31 December 2024 in Los
Angeles, which is already 2025 in UTC.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import distinct, func, select

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, Species, User

LA = ZoneInfo("America/Los_Angeles")


def _la(*args) -> datetime:
    return datetime(*args, tzinfo=LA).astimezone(timezone.utc)


async def _seed() -> dict:
    tag = secrets.token_hex(3)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(name="Lister", email=f"life_{tag}@test.dev", password_hash="x",
                        role="viewer", notify_email=False)
            db.add(user)
            await db.flush()
            front = Device(name="Front", owner_id=user.id, token=secrets.token_urlsafe(12))
            back = Device(name="Back", owner_id=user.id, token=secrets.token_urlsafe(12))
            db.add_all([front, back])
            await db.flush()

            def species(common, kind="bird"):
                return Species(common_name=common, genus=f"Life{tag}", species_name=common.lower(),
                               kind=kind, animal_group="squirrel" if kind == "animal" else None)

            cardinal, jay, wren = species("Life Cardinal"), species("Life Jay"), species("Life Wren")
            squirrel, unknown = species("Life Squirrel", "animal"), species("Unknown")
            db.add_all([cardinal, jay, wren, squirrel, unknown])
            await db.flush()

            visits = [
                (wren, back, _la(2023, 6, 1, 9, 0)),
                (cardinal, back, _la(2024, 3, 1, 10, 0)),
                (cardinal, front, _la(2024, 12, 31, 20, 0)),   # 2025 in UTC
                (cardinal, front, recent),
                (jay, front, recent),
                (squirrel, front, _la(2022, 5, 1, 12, 0)),     # an animal-only year
                (squirrel, front, recent),
                (unknown, front, recent),
            ]
            for sp, dev, when in visits:
                db.add(Sighting(species_id=sp.id, device_id=dev.id, datetime=when,
                                confidence_score=0.9, classification_tier_used="gpu", delayed=False))
            await db.flush()
            return {
                "user_id": user.id, "front": front.id, "back": back.id,
                "this_year": recent.astimezone(LA).year,
            }


@pytest.fixture(scope="module")
def lister(client):
    return asyncio.run(_seed())


def _get(client, lister, **params):
    headers = {"Authorization": f"Bearer {create_user_token(lister['user_id'], 'viewer')}"}
    return client.get("/stats/life-list", params=params, headers=headers)


def _list(client, lister, **params):
    res = _get(client, lister, **params)
    assert res.status_code == 200, res.text
    return res.json()


def _by_name(body):
    return {r["common_name"]: r for r in body["species"]}


async def _sql_distinct_birds(device_ids, year, zone) -> int:
    """Distinct bird species in a local year, counted straight from the tables."""
    lo = datetime(year, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    hi = datetime(year + 1, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    async with get_session_factory()() as db:
        return (
            await db.execute(
                select(func.count(distinct(Sighting.species_id)))
                .join(Species, Species.id == Sighting.species_id)
                .where(
                    Sighting.device_id.in_(device_ids),
                    Species.kind == "bird",
                    func.lower(Species.common_name) != "unknown",
                    Sighting.datetime >= lo,
                    Sighting.datetime < hi,
                )
            )
        ).scalar_one()


def test_each_year_list_matches_a_sql_count_of_distinct_birds(client, lister):
    tz = "America/Los_Angeles"
    years = _list(client, lister, tz=tz)["years"]
    assert years == [lister["this_year"], 2024, 2023]   # 2022 had only a squirrel
    for year in years:
        body = _list(client, lister, tz=tz, year=year)
        expected = asyncio.run(_sql_distinct_birds([lister["front"], lister["back"]], year, LA))
        assert len(body["species"]) == expected, year


def test_the_life_list_leaves_out_animals_and_unknown(client, lister):
    body = _list(client, lister, tz="America/Los_Angeles")
    assert body["year"] is None
    rows = _by_name(body)
    assert set(rows) == {"Life Cardinal", "Life Jay", "Life Wren"}
    # Newest first sighting first.
    assert [r["common_name"] for r in body["species"]] == ["Life Jay", "Life Cardinal", "Life Wren"]

    cardinal = rows["Life Cardinal"]
    assert cardinal["count"] == 3
    assert cardinal["first_feeder_name"] == "Back"
    assert cardinal["first_feeder_id"] == lister["back"]
    assert datetime.fromisoformat(cardinal["first_seen"]) == _la(2024, 3, 1, 10, 0)
    # For the life list, new means first recorded this year.
    assert rows["Life Jay"]["new_in_year"] is True
    assert cardinal["new_in_year"] is False
    assert rows["Life Wren"]["new_in_year"] is False


def test_a_year_list_counts_that_local_year_only(client, lister):
    rows = _by_name(_list(client, lister, tz="America/Los_Angeles", year=2024))
    assert set(rows) == {"Life Cardinal"}
    assert rows["Life Cardinal"]["count"] == 2
    assert rows["Life Cardinal"]["new_in_year"] is True     # first ever was March 2024

    # In UTC the 31 December visit is 2025, so 2024 keeps one visit.
    utc = _by_name(_list(client, lister, year=2024))
    assert utc["Life Cardinal"]["count"] == 1


def test_a_year_list_marks_only_species_first_seen_that_year(client, lister):
    rows = _by_name(_list(client, lister, tz="America/Los_Angeles", year=lister["this_year"]))
    assert set(rows) == {"Life Cardinal", "Life Jay"}
    assert rows["Life Jay"]["new_in_year"] is True
    assert rows["Life Cardinal"]["new_in_year"] is False
    assert rows["Life Cardinal"]["first_feeder_name"] == "Front"


def test_the_feeder_scope_covers_one_feeder(client, lister):
    tz = "America/Los_Angeles"
    body = _list(client, lister, tz=tz, device_id=lister["front"])
    assert body["years"] == [lister["this_year"], 2024]
    rows = _by_name(body)
    assert set(rows) == {"Life Cardinal", "Life Jay"}
    assert rows["Life Cardinal"]["first_feeder_name"] == "Front"
    assert datetime.fromisoformat(rows["Life Cardinal"]["first_seen"]) == _la(2024, 12, 31, 20, 0)

    # First at this feeder in 2024, though Back saw one in March.
    year = _by_name(_list(client, lister, tz=tz, year=2024, device_id=lister["front"]))
    assert year["Life Cardinal"]["new_in_year"] is True


def test_another_users_feeder_scopes_to_nothing(client, lister, owner_headers):
    res = client.get("/stats/life-list", params={"device_id": lister["front"]}, headers=owner_headers)
    assert res.status_code == 200
    assert res.json() == {"year": None, "years": [], "species": []}


def test_bad_year_and_zone_are_400(client, lister):
    assert _get(client, lister, year=1999).status_code == 400
    assert _get(client, lister, year=10000).status_code == 400
    assert _get(client, lister, tz="Mars/Olympus_Mons").status_code == 400
