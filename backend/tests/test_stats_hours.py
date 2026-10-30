"""GET /stats/hours and the local-hour fields on GET /stats/species-counts.

The visits sit on a throwaway device, never on the seeded ones, so the exact
counts in test_stats.py hold in any test order. SQLite has no AT TIME ZONE, so
this suite covers the Python path. integration_tests/test_api_postgres.py runs
the same assertions on the Postgres path.
"""
import asyncio
from datetime import timezone

import pytest

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.fixtures import HOUR_STATION_TZ, seed_hour_station
from backend.stats.operations import peak_hours
from backend.tests.conftest import IDS


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id, 'viewer')}"}


async def _make_station() -> dict:
    async with get_session_factory()() as db:
        async with db.begin():
            return await seed_hour_station(db, (IDS["spA_id"], IDS["spB_id"]))


@pytest.fixture(scope="module")
def station(client):
    return asyncio.run(_make_station())


def _hours(client, station, **params):
    return client.get("/stats/hours", params=params, headers=_auth(station["user_id"]))


def test_a_1900_local_visit_lands_in_hour_19(client, station):
    res = _hours(client, station, species_id=IDS["spA_id"], tz=HOUR_STATION_TZ)
    assert res.status_code == 200
    body = res.json()
    assert len(body["counts"]) == 24
    assert body["counts"][19] == 2
    assert body["counts"][8] == 1
    assert body["total"] == 3                  # the 60-day-old visit is outside 30 days
    assert body["peak_hours"] == [19, 8]
    assert body["earliest"] == "08:10"
    assert body["latest"] == "19:40"


def test_utc_is_the_default_and_moves_the_visit(client, station):
    body = _hours(client, station, species_id=IDS["spA_id"]).json()
    utc_hour = station["a_evening_1"].astimezone(timezone.utc).hour
    assert utc_hour != 19
    assert body["counts"][19] == 0
    assert body["counts"][utc_hour] >= 1


def test_days_zero_is_all_time(client, station):
    body = _hours(client, station, species_id=IDS["spA_id"], tz=HOUR_STATION_TZ, days=0).json()
    assert body["total"] == 4
    assert body["counts"][12] == 1


def test_no_species_filter_covers_every_species(client, station):
    body = _hours(client, station, tz=HOUR_STATION_TZ).json()
    assert body["total"] == 4                  # three of species A, one of species B
    assert body["counts"][6] == 1
    assert body["earliest"] == "06:30"


def test_unknown_zone_is_400(client, station):
    for tz in ("Mars/Olympus_Mons", "../../etc/passwd", ""):
        assert _hours(client, station, tz=tz).status_code == 400
    res = client.get(
        "/stats/species-counts", params={"tz": "Not/AZone"}, headers=_auth(station["user_id"])
    )
    assert res.status_code == 400


def test_bad_days_is_400(client, station):
    assert _hours(client, station, days=-1).status_code == 400
    assert _hours(client, station, days=10**9).status_code == 400


def test_hours_scoped_to_accessible_devices(client, station, viewer_headers):
    # The seeded viewer cannot see the station's device, so its visits do not count.
    # The viewer still sees the three species A visits that the base seed puts on
    # dev1 at "now". Their hour depends on when the suite runs, so check the total,
    # not fixed hours. The station's three in-window visits would make it six.
    body = client.get(
        "/stats/hours",
        params={"species_id": IDS["spA_id"], "tz": HOUR_STATION_TZ},
        headers=viewer_headers,
    ).json()
    assert body["total"] == 3
    assert sum(body["counts"]) == 3


def test_hours_with_no_visits(client, station):
    body = _hours(client, station, species_id=IDS["spC_id"], tz=HOUR_STATION_TZ).json()
    assert body == {
        "counts": [0] * 24, "total": 0, "peak_hours": [], "earliest": None, "latest": None,
    }


def test_species_counts_peak_hours_and_last_seen(client, station):
    rows = client.get(
        "/stats/species-counts",
        params={"tz": HOUR_STATION_TZ},
        headers=_auth(station["user_id"]),
    ).json()
    by_id = {r["id"]: r for r in rows}
    a, b = by_id[IDS["spA_id"]], by_id[IDS["spB_id"]]
    assert a["peak_hours"] == [19, 8]
    assert b["peak_hours"] == [6]
    assert a["count"] == 4                     # the count stays all time
    assert a["last_seen"].startswith(station["a_evening_1"].strftime("%Y-%m-%dT%H:%M"))


def test_species_counts_without_tz_has_no_peak_hours(client, station):
    rows = client.get("/stats/species-counts", headers=_auth(station["user_id"])).json()
    assert rows
    assert all(r["peak_hours"] is None for r in rows)
    assert all(r["last_seen"] is not None for r in rows)


def _day(**visits: int) -> list[int]:
    counts = [0] * 24
    for hour, n in visits.items():
        counts[int(hour[1:])] = n
    return counts


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([0] * 24, []),
        (_day(h7=1), [7]),                              # one visit, one petal
        (_day(h8=5, h9=5, h17=3), [8, 17]),             # a busy 8 and 9 am is one peak
        (_day(h8=5, h9=4, h10=1, h17=3, h18=2), [8, 17]),
        (_day(h23=4, h0=4, h12=1), [23, 12]),           # a peak can wrap past midnight
        ([2] * 24, [0]),                                # flat day falls back to the first hour
    ],
)
def test_peak_hours(counts, expected):
    assert peak_hours(counts) == expected
