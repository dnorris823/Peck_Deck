"""DELETE /sightings/{id}.

Every test deletes from a throwaway device, never from the seeded ones, so the
exact-count assertions elsewhere hold in any test order. The device owner has
the viewer role, which separates "owns the device" from "owner role".
"""
import asyncio
import secrets
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import backend.sightings.controller as sightings_controller
from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, DeviceUser, Sighting, User
from backend.events.hub import SightingDeleted
from backend.tests.conftest import IDS


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id, role)}"}


async def _make_station() -> dict:
    """A viewer-role device owner, a viewer member, and one sighting with an image."""
    async with get_session_factory()() as db:
        async with db.begin():
            def user(label):
                return User(
                    name=label, email=f"{label}_{secrets.token_hex(4)}@test.dev",
                    password_hash="x", role="viewer", notify_email=False,
                )

            owner, member = user("devowner"), user("member")
            db.add_all([owner, member])
            await db.flush()
            device = Device(name="Delete Device", owner_id=owner.id, token=secrets.token_urlsafe(12))
            db.add(device)
            await db.flush()
            db.add(DeviceUser(device_id=device.id, user_id=member.id))
            sighting = Sighting(
                species_id=IDS["spA_id"], device_id=device.id,
                datetime=datetime.now(timezone.utc), image_data=b"\xff\xd8\xff\xe0squirrel",
                classification_tier_used="gpu", confidence_score=0.9, delayed=False,
            )
            db.add(sighting)
            await db.flush()
            return {
                "owner_id": owner.id, "member_id": member.id,
                "device_id": device.id, "sighting_id": sighting.id,
            }


async def _row_exists(sighting_id: int) -> bool:
    async with get_session_factory()() as db:
        result = await db.execute(select(Sighting.id).where(Sighting.id == sighting_id))
        return result.scalar_one_or_none() is not None


@pytest.fixture
def station(client):
    return asyncio.run(_make_station())


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr(sightings_controller.sighting_hub, "publish", events.append)
    return events


def test_device_owner_deletes_the_row_and_its_image(client, station, published):
    sid = station["sighting_id"]
    headers = _auth(station["owner_id"], "viewer")
    assert client.get(f"/sightings/{sid}/image", headers=headers).status_code == 200

    res = client.delete(f"/sightings/{sid}", headers=headers)

    assert res.status_code == 204
    assert not asyncio.run(_row_exists(sid))
    assert client.get(f"/sightings/{sid}", headers=headers).status_code == 404
    assert client.get(f"/sightings/{sid}/image", headers=headers).status_code == 404
    assert published == [SightingDeleted(sighting_id=sid, device_id=station["device_id"])]


def test_viewer_on_the_device_gets_403(client, station, published):
    sid = station["sighting_id"]
    res = client.delete(f"/sightings/{sid}", headers=_auth(station["member_id"], "viewer"))

    assert res.status_code == 403
    assert asyncio.run(_row_exists(sid))
    assert published == []


def test_owner_role_deletes_on_a_device_it_does_not_own(client, station, owner_headers, published):
    sid = station["sighting_id"]
    res = client.delete(f"/sightings/{sid}", headers=owner_headers)

    assert res.status_code == 204
    assert not asyncio.run(_row_exists(sid))


def test_missing_sighting_is_404(client, owner_headers, published):
    assert client.delete("/sightings/987654321", headers=owner_headers).status_code == 404
    assert published == []


def test_requires_a_user_token(client, station):
    sid = station["sighting_id"]
    assert client.delete(f"/sightings/{sid}").status_code == 401
    # A device token is not accepted on a user route.
    assert client.delete(
        f"/sightings/{sid}", headers={"Authorization": "Bearer dev1-token"}
    ).status_code == 401
    assert asyncio.run(_row_exists(sid))
