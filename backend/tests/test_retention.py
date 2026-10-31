"""Database size in Settings, and the optional retention rule.

The rule deletes "Unknown" sightings older than ``RETENTION_UNKNOWN_DAYS``. It
is off by default, and when off it must delete nothing. When on it must delete
only the rows that match, and log how many.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from backend import retention
from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting
from backend.species.operations import get_or_create_species
from backend.tests.test_sightings_upload import _fresh_device_token

NOW = datetime.now(timezone.utc)


async def _add_sightings(rows: list[tuple[str, int]]) -> list[int]:
    """Add one sighting per ``(common_name, age_in_days)`` on a fresh device."""
    token = await _fresh_device_token()
    async with get_session_factory()() as db:
        async with db.begin():
            device_id = (
                await db.execute(select(Device.id).where(Device.token == token))
            ).scalar_one()
            ids = []
            for common_name, age in rows:
                species = await get_or_create_species(
                    db, common_name=common_name, genus=common_name, species_name="sp."
                )
                s = Sighting(
                    species_id=species.id,
                    device_id=device_id,
                    datetime=NOW - timedelta(days=age),
                    image_data=b"x" * 100,
                    classification_tier_used="none",
                    confidence_score=0.0,
                    delayed=False,
                )
                db.add(s)
                await db.flush()
                ids.append(s.id)
            return ids


async def _surviving(ids: list[int]) -> set[int]:
    async with get_session_factory()() as db:
        rows = await db.execute(select(Sighting.id).where(Sighting.id.in_(ids)))
        return set(rows.scalars())


async def _remove(ids: list[int]) -> None:
    async with get_session_factory()() as db:
        async with db.begin():
            await db.execute(delete(Sighting).where(Sighting.id.in_(ids)))


async def _count() -> int:
    async with get_session_factory()() as db:
        return (await db.execute(select(func.count(Sighting.id)))).scalar_one()


async def _apply(days: int) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            return await retention.delete_old_unknown(db, days)


def test_retention_is_off_by_default():
    assert settings.RETENTION_UNKNOWN_DAYS == 0


def test_retention_off_deletes_nothing(client):
    ids = asyncio.run(_add_sightings([("Unknown", 400), ("Unknown", 40)]))
    before = asyncio.run(_count())

    assert asyncio.run(_apply(0)) == 0

    assert asyncio.run(_count()) == before
    assert asyncio.run(_surviving(ids)) == set(ids)
    # Leave no old Unknown rows behind for the tests that turn the rule on.
    asyncio.run(_remove(ids))


def test_retention_on_deletes_only_old_unknown(client):
    old_unknown, new_unknown, old_named = asyncio.run(
        _add_sightings([("Unknown", 31), ("Unknown", 29), ("Retention Finch", 31)])
    )
    before = asyncio.run(_count())

    deleted = asyncio.run(_apply(30))

    # Seeded data has no old Unknown rows, so only the one added here matches.
    assert deleted == 1
    assert asyncio.run(_count()) == before - 1
    assert asyncio.run(_surviving([old_unknown, new_unknown, old_named])) == {
        new_unknown,
        old_named,
    }


def test_retention_run_logs_the_count(client, caplog):
    asyncio.run(_add_sightings([("Unknown", 90), ("Unknown", 91)]))

    with caplog.at_level(logging.INFO, logger="peckdeck.retention"):
        deleted = asyncio.run(retention.run_once(60))

    assert deleted == 2
    assert "retention: deleted 2 Unknown sightings older than 60 days" in caplog.text


def test_retention_refuses_a_negative_age():
    try:
        retention.start(-1)
    except RuntimeError as e:
        assert "RETENTION_UNKNOWN_DAYS" in str(e)
    else:
        raise AssertionError("a negative age must refuse to start")


def test_storage_reports_both_sizes(client, owner_headers):
    asyncio.run(_add_sightings([("Storage Finch", 0)]))

    res = client.get("/stats/storage", headers=owner_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["database_bytes"] > 0
    assert body["image_bytes"] >= 100
    assert body["image_bytes"] <= body["database_bytes"]
    assert body["retention_unknown_days"] == 0


def test_storage_requires_a_user(client):
    assert client.get("/stats/storage").status_code == 401
