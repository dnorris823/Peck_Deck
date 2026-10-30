"""PATCH /sightings/{id}, a person correcting a sighting's species.

Every test corrects a sighting on a throwaway device, never a seeded one, so
the exact-count assertions elsewhere hold in any test order. The device owner
has the viewer role, which separates "owns the device" from "owner role".
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
from backend.events.hub import SightingUpdated
from backend.tests.conftest import IDS
from backend.tests.test_sighting_image_loading import _READS_BYTES, _captured_selects

TRACE = [
    {"tier": "gpu", "outcome": "below_threshold", "confidence": 0.41, "threshold": 0.6},
    {"tier": "local", "outcome": "accepted", "confidence": 0.88, "threshold": 0.85},
]


def _auth(user_id: int, role: str = "viewer") -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id, role)}"}


async def _make_station() -> dict:
    """A device owner, a member, a stranger, and one sighting of species A."""
    async with get_session_factory()() as db:
        async with db.begin():
            def user(label):
                return User(
                    name=label, email=f"{label}_{secrets.token_hex(4)}@test.dev",
                    password_hash="x", role="viewer", notify_email=False,
                )

            owner, member, stranger = user("devowner"), user("member"), user("stranger")
            db.add_all([owner, member, stranger])
            await db.flush()
            device = Device(name="Correct Device", owner_id=owner.id, token=secrets.token_urlsafe(12))
            db.add(device)
            await db.flush()
            db.add(DeviceUser(device_id=device.id, user_id=member.id))
            sighting = Sighting(
                species_id=IDS["spA_id"], device_id=device.id,
                datetime=datetime.now(timezone.utc), image_data=b"\xff\xd8\xff\xe0finch",
                classification_tier_used="local", confidence_score=0.88, delayed=False,
                tier_trace=TRACE,
            )
            db.add(sighting)
            await db.flush()
            return {
                "owner_id": owner.id, "member_id": member.id, "stranger_id": stranger.id,
                "device_id": device.id, "sighting_id": sighting.id,
            }


async def _row(sighting_id: int) -> Sighting:
    async with get_session_factory()() as db:
        result = await db.execute(select(Sighting).where(Sighting.id == sighting_id))
        return result.scalar_one()


@pytest.fixture
def station(client):
    return asyncio.run(_make_station())


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr(sightings_controller.sighting_hub, "publish", events.append)
    return events


def _correct(client, station, user_key="owner_id", species_key="spB_id", role="viewer"):
    return client.patch(
        f"/sightings/{station['sighting_id']}",
        json={"species_id": IDS[species_key]},
        headers=_auth(station[user_key], role),
    )


def test_device_owner_corrects_the_species(client, station, published):
    res = _correct(client, station)

    assert res.status_code == 200
    body = res.json()
    assert body["species_id"] == IDS["spB_id"]
    assert body["original_species_id"] == IDS["spA_id"]
    assert body["corrected_by"] == station["owner_id"]
    assert body["corrected_at"] is not None
    assert body["has_image"] is True

    row = asyncio.run(_row(station["sighting_id"]))
    assert row.species_id == IDS["spB_id"]
    assert row.original_species_id == IDS["spA_id"]
    assert row.corrected_by == station["owner_id"]


def test_the_pi_answer_is_kept(client, station, published):
    body = _correct(client, station).json()

    assert body["classification_tier_used"] == "local"
    assert body["confidence_score"] == 0.88
    assert body["tier_trace"] == TRACE
    fetched = client.get(f"/sightings/{station['sighting_id']}", headers=_auth(station["owner_id"]))
    assert fetched.json()["tier_trace"] == TRACE


def test_a_second_correction_keeps_the_first_original(client, station, published):
    _correct(client, station, species_key="spB_id")
    body = _correct(client, station, user_key="member_id", species_key="spC_id").json()

    assert body["species_id"] == IDS["spC_id"]
    assert body["original_species_id"] == IDS["spA_id"]
    assert body["corrected_by"] == station["member_id"]


def test_a_member_of_the_device_may_correct(client, station, published):
    assert _correct(client, station, user_key="member_id").status_code == 200


def test_a_user_without_access_gets_403(client, station, published):
    res = _correct(client, station, user_key="stranger_id")

    assert res.status_code == 403
    assert asyncio.run(_row(station["sighting_id"])).species_id == IDS["spA_id"]
    assert published == []


def test_owner_role_corrects_on_a_device_it_does_not_own(client, station, owner_headers, published):
    res = client.patch(
        f"/sightings/{station['sighting_id']}",
        json={"species_id": IDS["spB_id"]}, headers=owner_headers,
    )
    assert res.status_code == 200


def test_missing_sighting_is_404(client, owner_headers, published):
    res = client.patch("/sightings/987654321", json={"species_id": IDS["spB_id"]}, headers=owner_headers)
    assert res.status_code == 404
    assert published == []


def test_unknown_species_is_400(client, station, published):
    res = client.patch(
        f"/sightings/{station['sighting_id']}",
        json={"species_id": 987654321}, headers=_auth(station["owner_id"]),
    )
    assert res.status_code == 400
    assert asyncio.run(_row(station["sighting_id"])).corrected_at is None
    assert published == []


def test_requires_a_user_token(client, station):
    sid = station["sighting_id"]
    body = {"species_id": IDS["spB_id"]}
    assert client.patch(f"/sightings/{sid}", json=body).status_code == 401
    # A device token is not accepted on a user route.
    assert client.patch(
        f"/sightings/{sid}", json=body, headers={"Authorization": "Bearer dev1-token"}
    ).status_code == 401


def test_open_tabs_hear_of_it(client, station, published):
    body = _correct(client, station).json()

    assert published == [
        SightingUpdated(
            sighting_id=station["sighting_id"], device_id=station["device_id"], payload=body,
        )
    ]


def test_does_not_read_image_bytes(client, station, published):
    with _captured_selects() as statements:
        assert _correct(client, station).status_code == 200

    assert statements, "the listener saw no SELECT, so it is not attached"
    assert not [s for s in statements if _READS_BYTES.search(s)]


def test_stats_count_the_corrected_species(client, station, published):
    headers = _auth(station["owner_id"])

    def counts():
        rows = client.get("/stats/species-counts", headers=headers).json()
        return {r["id"]: r["count"] for r in rows}

    def hours_total(species_key):
        res = client.get(
            "/stats/hours", params={"species_id": IDS[species_key], "days": 30}, headers=headers,
        )
        return res.json()["total"]

    assert counts() == {IDS["spA_id"]: 1}
    assert hours_total("spA_id") == 1

    _correct(client, station)

    assert counts() == {IDS["spB_id"]: 1}
    assert hours_total("spA_id") == 0
    assert hours_total("spB_id") == 1
