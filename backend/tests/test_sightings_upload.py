"""Tests for the Pi-facing sighting upload path (POST /sightings).

The Pi authenticates with a *device* token and uploads image bytes + metadata
as a single multipart POST. These tests cover the offline-sync / delayed flow
in particular (a sighting captured while the Pi was offline and synced later).

Each test uploads to a **fresh** device owned by a throwaway user, so the
sightings never land on a device the seeded ``owner@test.dev`` can access — that
keeps the exact-count assertions in ``test_sightings.py`` stable regardless of
test order. The two fire-and-forget side effects (notification dispatch and the
Wikipedia URL backfill) are patched to network-free no-ops.
"""
import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import backend.sightings.aftercare as sighting_aftercare
from backend.database.connection import get_session_factory
from backend.database.models import Device, User

_JPEG = b"\xff\xd8\xff\xe0delayed-sync-bytes"


async def _fresh_device_token() -> str:
    """Create a throwaway owner + device and return the device's token."""
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(
                name="Upload Owner",
                email=f"upload_{secrets.token_hex(4)}@test.dev",
                password_hash="x",
                role="owner",
                notify_email=False,
            )
            db.add(u)
            await db.flush()
            token = secrets.token_urlsafe(12)
            d = Device(
                name="Upload Device",
                owner_id=u.id,
                token=token,
            )
            db.add(d)
            await db.flush()
            return token


def _silence_side_effects(monkeypatch):
    """Patch the two fire-and-forget tasks so no network/DB races occur."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _noop)


def _upload(client, token, *, delayed, image=_JPEG, tier_trace=None):
    data = {
        "timestamp": "2026-07-19T10:30:00",
        "common_name": "Sync Sparrow",
        "scientific_name": "Passer testus",
        "confidence_score": "0.77",
        "classification_tier_used": "local",
        "delayed": delayed,
    }
    if tier_trace is not None:
        data["tier_trace"] = tier_trace
    return client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        files={"image": ("bird.jpg", image, "image/jpeg")},
    )


def test_delayed_upload_persists_and_flags_delayed(client, owner_headers, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, delayed="true")
    assert res.status_code == 201
    body = res.json()
    assert body["delayed"] is True
    assert body["has_image"] is True
    assert body["classification_tier_used"] == "local"
    assert body["confidence_score"] == 0.77

    # Round-trips: the synced sighting is retrievable and the image is served.
    sid = body["id"]
    got = client.get(f"/sightings/{sid}", headers=owner_headers)
    assert got.status_code == 200
    assert got.json()["delayed"] is True

    img = client.get(f"/sightings/{sid}/image", headers=owner_headers)
    assert img.status_code == 200
    assert img.content == _JPEG
    assert img.headers["content-type"] == "image/jpeg"


def test_live_upload_defaults_delayed_false(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    # Omit the `delayed` field entirely — it must default to false.
    res = client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "timestamp": "2026-07-19T11:00:00",
            "common_name": "Live Finch",
            "scientific_name": "Fringilla testus",
            "confidence_score": "0.9",
            "classification_tier_used": "gpu",
        },
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )
    assert res.status_code == 201
    assert res.json()["delayed"] is False


def test_upload_without_image_has_no_image(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    # An empty image part is allowed (metadata-only sync); has_image is False.
    res = _upload(client, token, delayed="true", image=b"")
    assert res.status_code == 201
    assert res.json()["has_image"] is False


def test_upload_requires_device_token(client, owner_headers):
    # A user JWT is not a device token — device_guard rejects the upload.
    res = client.post(
        "/sightings",
        headers=owner_headers,
        data={
            "timestamp": "2026-07-19T11:00:00",
            "common_name": "X",
            "scientific_name": "X y",
            "confidence_score": "0.5",
            "classification_tier_used": "local",
        },
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )
    assert res.status_code == 401


async def _last_seen(token: str):
    async with get_session_factory()() as db:
        result = await db.execute(select(Device.last_seen).where(Device.token == token))
        return result.scalar_one()


def test_upload_marks_device_seen(client, monkeypatch):
    # An uploading station is alive. Before this, a Pi that never sent a
    # heartbeat read "offline" minutes after a sighting.
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())
    assert asyncio.run(_last_seen(token)) is None

    # Delayed on purpose: the capture time is old, but the station is up now.
    res = _upload(client, token, delayed="true")
    assert res.status_code == 201

    seen = asyncio.run(_last_seen(token))
    assert seen is not None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - seen < timedelta(minutes=1)


# ── Tier trace ───────────────────────────────────────────────────────────────

# Tier 2 unreachable, Tier 1 answered. The case the trace exists for.
_TRACE = [
    {"tier": "gpu", "outcome": "failed", "confidence": None, "threshold": 0.6},
    {"tier": "local", "outcome": "accepted", "confidence": 0.77, "threshold": 0.85},
]


def test_upload_stores_and_returns_the_tier_trace(client, owner_headers, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, delayed="false", tier_trace=json.dumps(_TRACE))
    assert res.status_code == 201
    assert res.json()["tier_trace"] == _TRACE

    got = client.get(f"/sightings/{res.json()['id']}", headers=owner_headers)
    assert got.json()["tier_trace"] == _TRACE


def test_upload_without_a_tier_trace_returns_null(client, monkeypatch):
    """An older Pi build sends no trace. The upload still lands."""
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())

    res = _upload(client, token, delayed="false")

    assert res.status_code == 201
    assert res.json()["tier_trace"] is None


def test_every_tier_failed_round_trips(client, monkeypatch):
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())
    trace = [
        {"tier": "gpu", "outcome": "failed", "confidence": None, "threshold": 0.6},
        {"tier": "local", "outcome": "failed", "confidence": None, "threshold": 0.85},
    ]

    res = client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "timestamp": "2026-07-19T12:00:00",
            "common_name": "Unknown",
            "scientific_name": "",
            "confidence_score": "0.0",
            "classification_tier_used": "none",
            "tier_trace": json.dumps(trace),
        },
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )

    assert res.status_code == 201
    assert res.json()["classification_tier_used"] == "none"
    assert res.json()["tier_trace"] == trace


def test_a_malformed_tier_trace_keeps_the_sighting(client, monkeypatch):
    """A 4xx would make the Pi drop the visit, so a bad trace stores null."""
    _silence_side_effects(monkeypatch)
    token = asyncio.run(_fresh_device_token())
    bad_outcome = [{**_TRACE[0], "outcome": "maybe"}]

    for raw in ("not json", json.dumps({"tier": "gpu"}), json.dumps(bad_outcome)):
        res = _upload(client, token, delayed="false", tier_trace=raw)
        assert res.status_code == 201, raw
        assert res.json()["tier_trace"] is None, raw
