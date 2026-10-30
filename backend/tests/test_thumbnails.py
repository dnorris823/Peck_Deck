"""Thumbnails for the gallery grids.

The upload makes a thumbnail, ``GET /sightings/{id}/image?size=thumb`` serves
it, and a sighting without one serves its full image instead. An image Pillow
cannot decode must still upload.
"""
import asyncio
import io
import logging

from PIL import Image
from sqlalchemy import select

from backend.auth.jwt_utils import create_user_token
from backend.backfill_thumbnails import backfill
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting
from backend.sightings.thumbnails import THUMBNAIL_SIZE, make_thumbnail
from backend.tests.test_sightings_upload import _fresh_device_token, _silence_side_effects, _upload

_GARBAGE = b"\xff\xd8\xff\xe0not-really-a-jpeg"


def _jpeg(width=1600, height=1200) -> bytes:
    out = io.BytesIO()
    Image.effect_noise((width, height), 64).convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


async def _owner_of_device_with_token(token: str) -> int:
    async with get_session_factory()() as db:
        return (await db.execute(select(Device.owner_id).where(Device.token == token))).scalar_one()


async def _thumbnail_of(sighting_id: int) -> bytes | None:
    async with get_session_factory()() as db:
        return (
            await db.execute(select(Sighting.thumbnail_data).where(Sighting.id == sighting_id))
        ).scalar_one()


def _upload_as_owner(client, monkeypatch, image: bytes) -> tuple[int, dict]:
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())
    res = _upload(client, token, delayed="false", image=image)
    assert res.status_code == 201
    owner_id = asyncio.run(_owner_of_device_with_token(token))
    return res.json()["id"], {"Authorization": f"Bearer {create_user_token(owner_id, 'owner')}"}


def test_make_thumbnail_fits_the_long_side():
    thumb = make_thumbnail(_jpeg(1600, 900))

    with Image.open(io.BytesIO(thumb)) as img:
        assert img.format == "JPEG"
        assert img.size == (THUMBNAIL_SIZE, 225)


def test_make_thumbnail_returns_none_for_bytes_it_cannot_decode(caplog):
    with caplog.at_level(logging.WARNING, logger="peckdeck.sightings"):
        assert make_thumbnail(_GARBAGE) is None
    assert "could not make a thumbnail" in caplog.text


def test_upload_stores_a_thumbnail_and_serves_it(client, monkeypatch):
    image = _jpeg()
    sighting_id, headers = _upload_as_owner(client, monkeypatch, image)

    thumb = asyncio.run(_thumbnail_of(sighting_id))
    assert thumb is not None
    assert len(thumb) < len(image) / 4

    res = client.get(f"/sightings/{sighting_id}/image?size=thumb", headers=headers)
    assert res.status_code == 200
    assert res.content == thumb
    assert res.headers["cache-control"] == "private, max-age=31536000, immutable"

    # The detail view's main photo still gets the full capture.
    full = client.get(f"/sightings/{sighting_id}/image", headers=headers)
    assert full.content == image
    assert client.get(f"/sightings/{sighting_id}/image?size=full", headers=headers).content == image


def test_undecodable_upload_still_stores_and_falls_back_to_the_full_image(client, monkeypatch):
    sighting_id, headers = _upload_as_owner(client, monkeypatch, _GARBAGE)

    assert asyncio.run(_thumbnail_of(sighting_id)) is None

    res = client.get(f"/sightings/{sighting_id}/image?size=thumb", headers=headers)
    assert res.status_code == 200
    assert res.content == _GARBAGE
    # Short-lived, so the real thumbnail replaces it once one exists.
    assert res.headers["cache-control"] == "private, max-age=86400"


def test_unknown_size_is_rejected(client, monkeypatch):
    sighting_id, headers = _upload_as_owner(client, monkeypatch, _GARBAGE)

    res = client.get(f"/sightings/{sighting_id}/image?size=huge", headers=headers)

    assert res.status_code == 400


def test_thumb_of_a_sighting_with_no_image_is_404(client, monkeypatch):
    sighting_id, headers = _upload_as_owner(client, monkeypatch, b"")

    res = client.get(f"/sightings/{sighting_id}/image?size=thumb", headers=headers)

    assert res.status_code == 404


async def _clear_thumbnail(sighting_id: int) -> None:
    async with get_session_factory()() as db:
        async with db.begin():
            row = await db.get(Sighting, sighting_id)
            row.thumbnail_data = None


def test_backfill_fills_missing_thumbnails_and_skips_bad_images(client, monkeypatch):
    good_id, _ = _upload_as_owner(client, monkeypatch, _jpeg())
    bad_id, _ = _upload_as_owner(client, monkeypatch, _GARBAGE)
    asyncio.run(_clear_thumbnail(good_id))

    made, failed = asyncio.run(backfill(batch_size=2, workers=1))

    assert made >= 1
    assert failed >= 1
    assert asyncio.run(_thumbnail_of(good_id)) is not None
    assert asyncio.run(_thumbnail_of(bad_id)) is None
