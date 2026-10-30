"""The sighting list and export never read image bytes.

Both only need to know whether a sighting has an image. Selecting the whole
``Sighting`` row reads every JPEG in the page into the API process to answer
that. These tests watch the SQL each query sends and fail if a SELECT reads
``image_data`` or ``thumbnail_data`` as a column again.

The rows go on a fresh device owned by a throwaway user, so the exact counts in
``test_sightings.py`` and ``test_export.py`` stay stable whatever the test order.
"""
import asyncio
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.engine import Engine

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, User
from backend.sightings.export import collect_rows
from backend.sightings.operations import list_sightings
from backend.tests.conftest import IDS

_JPEG = b"\xff\xd8\xff\xe0image-loading-bytes"

# `sightings.image_data IS NOT NULL` is the flag and is allowed. The bare column
# is the bytes. The thumbnail is bytes too, and no list query needs its flag.
_READS_BYTES = re.compile(r"sightings\.(?:image_data(?! IS NOT NULL)|thumbnail_data)")


async def _make_owner_with_two_sightings() -> dict:
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(
                name="Image Owner",
                email=f"images_{secrets.token_hex(4)}@test.dev",
                password_hash="x",
                role="owner",
                notify_email=False,
            )
            db.add(user)
            await db.flush()
            device = Device(name="Image Device", owner_id=user.id, token=secrets.token_urlsafe(12))
            db.add(device)
            await db.flush()
            with_image = Sighting(
                species_id=IDS["spA_id"],
                device_id=device.id,
                datetime=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                image_data=_JPEG,
                classification_tier_used="gpu",
                confidence_score=0.9,
            )
            without_image = Sighting(
                species_id=IDS["spA_id"],
                device_id=device.id,
                datetime=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
                image_data=None,
                classification_tier_used="gpu",
                confidence_score=0.9,
            )
            db.add_all([with_image, without_image])
            await db.flush()
            return {
                "user_id": user.id,
                "with_image": with_image.id,
                "without_image": without_image.id,
            }


@contextmanager
def _captured_selects():
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


async def _list(user_id: int):
    async with get_session_factory()() as db:
        rows = await list_sightings(
            db, user_id, device_id=None, species_id=None,
            from_date=None, to_date=None, limit=100, offset=0,
        )
        return {s.id: has_image for s, has_image in rows}


async def _export(user_id: int):
    async with get_session_factory()() as db:
        return await collect_rows(db, user_id)


def test_list_query_does_not_read_image_bytes(client):
    ids = asyncio.run(_make_owner_with_two_sightings())

    with _captured_selects() as statements:
        flags = asyncio.run(_list(ids["user_id"]))

    assert flags == {ids["with_image"]: True, ids["without_image"]: False}
    assert statements, "the listener saw no SELECT, so it is not attached"
    assert not [s for s in statements if _READS_BYTES.search(s)]


def test_export_query_does_not_read_image_bytes(client):
    ids = asyncio.run(_make_owner_with_two_sightings())

    with _captured_selects() as statements:
        rows = asyncio.run(_export(ids["user_id"]))

    by_id = {r["sighting_id"]: r for r in rows}
    assert by_id[ids["with_image"]]["has_image"] is True
    assert by_id[ids["with_image"]]["image_url"] == f"/sightings/{ids['with_image']}/image"
    assert by_id[ids["without_image"]]["has_image"] is False
    assert by_id[ids["without_image"]]["image_url"] == ""
    assert statements, "the listener saw no SELECT, so it is not attached"
    assert not [s for s in statements if _READS_BYTES.search(s)]


def test_list_route_reports_has_image(client):
    ids = asyncio.run(_make_owner_with_two_sightings())
    headers = {"Authorization": f"Bearer {create_user_token(ids['user_id'], 'owner')}"}

    res = client.get("/sightings?limit=100", headers=headers)

    assert res.status_code == 200
    flags = {s["id"]: s["has_image"] for s in res.json()}
    assert flags == {ids["with_image"]: True, ids["without_image"]: False}


def test_image_is_cacheable_by_the_browser_only(client):
    ids = asyncio.run(_make_owner_with_two_sightings())
    headers = {"Authorization": f"Bearer {create_user_token(ids['user_id'], 'owner')}"}

    res = client.get(f"/sightings/{ids['with_image']}/image", headers=headers)

    assert res.status_code == 200
    assert res.content == _JPEG
    assert res.headers["cache-control"] == "private, max-age=31536000, immutable"
