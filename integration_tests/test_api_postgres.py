"""Task 3.1 — API integration against a real ``postgres:16`` database.

These run the full Litestar app (real routing, guards, SQLAlchemy async engine)
against PostgreSQL rather than SQLite, so they catch dialect-specific behavior
the unit suite can't: ``bytea`` image storage, ``asyncpg`` type coercion, and
timezone-aware timestamps.
"""
import asyncio
import secrets

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.sightings.controller as sighting_controller
from backend.config import settings
from backend.database.models import Device, User

_JPEG = b"\xff\xd8\xff\xe0" + b"postgres-bytea-round-trip" * 64  # a few KB of bytes


def test_backend_is_running_on_postgres():
    # Guard against silently falling back to SQLite and calling it an
    # "integration" run.
    assert settings.DATABASE_URL.startswith("postgresql")


def test_login_with_real_bcrypt(client):
    res = client.post("/login", json={"email": "owner@test.dev", "password": "ownerpw"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    bad = client.post("/login", json={"email": "owner@test.dev", "password": "wrong"})
    assert bad.status_code == 401


def test_owner_and_viewer_see_scoped_sightings(client, owner_headers, viewer_headers):
    owner = client.get("/sightings", headers=owner_headers)
    assert owner.status_code == 200
    # dev1 (5) + dev2 (1) + dev3 (0) — everything the owner owns.
    assert len(owner.json()) == 6

    viewer = client.get("/sightings", headers=viewer_headers)
    assert viewer.status_code == 200
    # viewer is a member of dev1 only → the 5 dev1 sightings, none from dev2.
    assert len(viewer.json()) == 5


def _fresh_device_token() -> str:
    """Create a throwaway owner + device directly in Postgres.

    Uses its own short-lived engine created inside this ``asyncio.run`` loop:
    asyncpg connections are bound to the loop that opened them, so we must not
    reuse the app's engine (which lives on the TestClient's loop).
    """
    async def _make() -> str:
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                async with db.begin():
                    u = User(
                        name="PG Upload Owner",
                        email=f"pg_{secrets.token_hex(4)}@test.dev",
                        password_hash="x", role="owner",
                        notify_email=False, notify_sms=False,
                    )
                    db.add(u)
                    await db.flush()
                    token = secrets.token_urlsafe(12)
                    db.add(Device(name="PG Upload Device", owner_id=u.id,
                                  classification_tier="auto", token=token))
                    return token
        finally:
            await engine.dispose()

    return asyncio.run(_make())


def test_image_bytea_round_trips_through_postgres(client, owner_headers, monkeypatch):
    """A JPEG uploaded by the Pi is stored as bytea and served back byte-for-byte."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_controller.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_controller, "update_species_wiki_url", _noop)

    token = _fresh_device_token()
    res = client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "timestamp": "2026-07-19T10:30:00+00:00",
            "common_name": "Test Cardinal",       # matches a seeded species → no wiki backfill
            "scientific_name": "Cardinalis testus",
            "confidence_score": "0.83",
            "classification_tier_used": "gpu",
        },
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )
    assert res.status_code == 201, res.text
    sid = res.json()["id"]
    assert res.json()["has_image"] is True

    img = client.get(f"/sightings/{sid}/image", headers=owner_headers)
    assert img.status_code == 200
    assert img.content == _JPEG          # exact bytea round-trip
    assert img.headers["content-type"] == "image/jpeg"


def test_stats_aggregate_over_postgres(client, owner_headers):
    res = client.get("/stats/dashboard", headers=owner_headers)
    assert res.status_code == 200
    body = res.json()
    # The owner's seeded dataset: most-frequent species is the Cardinal (4 visits),
    # two species have any sightings, three devices registered.
    assert body["most_frequent"] == "Test Cardinal"
    assert body["most_frequent_count"] == 4
    assert body["total_species"] == 2
    assert body["total_devices"] == 3

    heat = client.get("/stats/heatmap", headers=owner_headers)
    assert heat.status_code == 200
    grid = heat.json()
    assert len(grid) == 7 and all(len(row) == 24 for row in grid)
    assert sum(sum(row) for row in grid) == 6   # all six seeded sightings, last 7d
