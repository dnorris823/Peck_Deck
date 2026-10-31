"""DELETE /sightings/{id}, POST /sightings/delete, and DELETE /devices/{id}/sightings.

Every test deletes from a throwaway device, never from the seeded ones, so the
exact-count assertions elsewhere hold in any test order. The device owner has
the viewer role, which separates "owns the device" from "owner role".
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import backend.sightings.controller as sightings_controller
from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, DeviceUser, Sighting, User
from backend.events.hub import SightingDeleted, SightingsDeleted
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
    # One hub object. Both controllers publish through it.
    events = []
    monkeypatch.setattr(sightings_controller.sighting_hub, "publish", events.append)
    return events


async def _add_sightings(device_id: int, days_ago: list[int]) -> list[int]:
    """More sightings on the station's device, each `days_ago` days old."""
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as db:
        async with db.begin():
            rows = [
                Sighting(
                    species_id=IDS["spA_id"], device_id=device_id,
                    datetime=now - timedelta(days=d), image_data=b"\xff\xd8test",
                    classification_tier_used="gpu", confidence_score=0.9, delayed=False,
                )
                for d in days_ago
            ]
            db.add_all(rows)
            await db.flush()
            return [r.id for r in rows]


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


# --- POST /sightings/delete ---

def test_bulk_delete_removes_the_listed_rows_only(client, station, published):
    extra = asyncio.run(_add_sightings(station["device_id"], [1, 2]))
    headers = _auth(station["owner_id"], "viewer")

    res = client.post("/sightings/delete", json={"ids": [station["sighting_id"], extra[0]]},
                      headers=headers)

    assert res.status_code == 200
    assert res.json() == {"deleted": 2}
    assert not asyncio.run(_row_exists(station["sighting_id"]))
    assert not asyncio.run(_row_exists(extra[0]))
    assert asyncio.run(_row_exists(extra[1]))
    assert published == [SightingsDeleted(device_id=station["device_id"], count=2)]


def test_bulk_delete_is_all_or_nothing(client, station, published):
    # Dev One's sighting belongs to the seeded owner, not to this device owner.
    seeded = client.get("/sightings?device_id=%d&limit=1" % IDS["dev1_id"],
                        headers=_auth(IDS["owner_id"], "owner")).json()[0]["id"]
    res = client.post("/sightings/delete", json={"ids": [station["sighting_id"], seeded]},
                      headers=_auth(station["owner_id"], "viewer"))

    assert res.status_code == 403
    assert asyncio.run(_row_exists(station["sighting_id"]))
    assert asyncio.run(_row_exists(seeded))
    assert published == []


def test_bulk_delete_by_a_member_is_403(client, station, published):
    res = client.post("/sightings/delete", json={"ids": [station["sighting_id"]]},
                      headers=_auth(station["member_id"], "viewer"))
    assert res.status_code == 403
    assert asyncio.run(_row_exists(station["sighting_id"]))


def test_bulk_delete_skips_missing_ids(client, station, published):
    res = client.post("/sightings/delete", json={"ids": [station["sighting_id"], 987654321]},
                      headers=_auth(station["owner_id"], "viewer"))
    assert res.json() == {"deleted": 1}

    again = client.post("/sightings/delete", json={"ids": [987654321]}, headers=_auth(station["owner_id"], "viewer"))
    assert again.status_code == 200
    assert again.json() == {"deleted": 0}
    assert published == [SightingsDeleted(device_id=station["device_id"], count=1)]


def test_bulk_delete_refuses_no_ids_and_too_many(client, owner_headers, published):
    assert client.post("/sightings/delete", json={"ids": []}, headers=owner_headers).status_code == 400
    too_many = list(range(1, sightings_controller.MAX_BULK_DELETE + 2))
    assert client.post("/sightings/delete", json={"ids": too_many}, headers=owner_headers).status_code == 400


def test_bulk_delete_requires_a_user_token(client, station):
    body = {"ids": [station["sighting_id"]]}
    assert client.post("/sightings/delete", json=body).status_code == 401
    assert client.post("/sightings/delete", json=body,
                       headers={"Authorization": "Bearer dev1-token"}).status_code == 401


# --- GET /devices/{id}/sightings/count and DELETE /devices/{id}/sightings ---

def test_delete_before_a_date_counts_then_removes_only_older_rows(client, station, published):
    old = asyncio.run(_add_sightings(station["device_id"], [40, 50, 60]))
    headers = _auth(station["owner_id"], "viewer")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    path = "/devices/%d/sightings" % station["device_id"]

    count = client.get(path + "/count", params={"before": cutoff}, headers=headers)
    assert count.status_code == 200
    assert count.json() == {"count": 3}

    res = client.delete(path, params={"before": cutoff}, headers=headers)
    assert res.status_code == 204
    assert not any(asyncio.run(_row_exists(i)) for i in old)
    # Today's sighting is newer than the cutoff, so it stays.
    assert asyncio.run(_row_exists(station["sighting_id"]))
    assert published == [SightingsDeleted(device_id=station["device_id"], count=3)]
    assert client.get(path + "/count", params={"before": cutoff}, headers=headers).json() == {"count": 0}


def test_delete_before_a_date_with_nothing_older_publishes_nothing(client, station, published):
    res = client.delete("/devices/%d/sightings" % station["device_id"],
                        params={"before": "2001-01-01"}, headers=_auth(station["owner_id"], "viewer"))
    assert res.status_code == 204
    assert published == []


def test_delete_before_a_date_is_owner_only(client, station, published):
    path = "/devices/%d/sightings" % station["device_id"]
    member = _auth(station["member_id"], "viewer")
    assert client.get(path + "/count", params={"before": "2100-01-01"}, headers=member).status_code == 403
    assert client.delete(path, params={"before": "2100-01-01"}, headers=member).status_code == 403
    assert asyncio.run(_row_exists(station["sighting_id"]))


def test_delete_before_a_date_needs_a_valid_date(client, station, published):
    path = "/devices/%d/sightings" % station["device_id"]
    headers = _auth(station["owner_id"], "viewer")
    assert client.delete(path, headers=headers).status_code == 400
    assert client.delete(path, params={"before": "last week"}, headers=headers).status_code == 400
    assert client.get(path + "/count", params={"before": "nope"}, headers=headers).status_code == 400
    assert client.delete("/devices/999999/sightings", params={"before": "2100-01-01"},
                         headers=headers).status_code == 404
    assert asyncio.run(_row_exists(station["sighting_id"]))
