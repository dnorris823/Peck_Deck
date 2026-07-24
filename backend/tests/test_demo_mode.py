"""Demo mode — read-only enforcement and instance metadata (FLEDGE Phase 5).

Demo mode's whole security surface is the allowlist in :mod:`backend.demo`: the
middleware runs before any guard, so it decides by method+path alone. These
tests pin both halves of that decision — what must be refused (every
user-facing write) and what must keep working (login, and the device-token
routes the Pi and the simulator drive).

``settings.DEMO_MODE`` is monkeypatched rather than set in the environment
because the app is built once per session; the middleware reads the flag per
request precisely so this works.
"""
import asyncio
import secrets

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.sightings.controller as sighting_controller
from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Base, Device, Sighting, Species, User
from backend.demo import is_write_allowed, maybe_seed_demo
from backend.fixtures import OWNER_PASSWORD
from backend.seed import owner_exists, seed_demo_data


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    return True


async def _fresh_device_token() -> str:
    """A throwaway device so demo-mode uploads don't perturb count assertions."""
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(
                name="Demo Owner",
                email=f"demo_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="owner",
                notify_email=False, notify_sms=False,
            )
            db.add(u)
            await db.flush()
            token = secrets.token_urlsafe(12)
            db.add(Device(name="Demo Device", owner_id=u.id,
                          classification_tier="auto", token=token))
            return token


# ---------------------------------------------------------------------------
# The allowlist itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", [
    ("GET", "/sightings"),
    ("GET", "/users/me"),
    ("HEAD", "/species"),
    ("OPTIONS", "/users"),          # CORS preflight must survive
    ("POST", "/login"),             # a demo you can't sign into isn't a demo
    ("POST", "/sightings"),         # device_guard — the Pi / the simulator
    ("POST", "/sightings/"),        # same route, trailing slash
    ("POST", "/classify"),          # device_guard — Tier 3 relay
    ("POST", "/devices/7/heartbeat"),
])
def test_allowed_in_demo_mode(method, path):
    assert is_write_allowed(method, path) is True


@pytest.mark.parametrize("method,path", [
    ("POST", "/users"),
    ("PUT", "/users/1"),
    ("POST", "/users/1/password"),
    ("PUT", "/users/me/preferences"),
    ("POST", "/devices"),
    ("PUT", "/devices/1"),
    ("POST", "/devices/1/users"),
    ("DELETE", "/devices/1/users/2"),
    ("POST", "/species"),
])
def test_blocked_in_demo_mode(method, path):
    assert is_write_allowed(method, path) is False


def test_heartbeat_allowlist_is_not_a_device_route_wildcard():
    """The device-id pattern must not open up the rest of /devices/{id}/*."""
    assert is_write_allowed("POST", "/devices/1/users") is False
    assert is_write_allowed("DELETE", "/devices/1/heartbeat/../users/2") is False


def test_allowlist_is_inert_when_demo_mode_is_off(client, owner_headers):
    """Sanity: the normal suite runs with DEMO_MODE off, so writes still work."""
    assert settings.DEMO_MODE is False
    res = client.post(
        "/users", headers=owner_headers,
        json={"name": "Not Demo", "email": f"notdemo_{secrets.token_hex(4)}@test.dev",
              "password": "pw12345678"},
    )
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# Enforcement over real HTTP
# ---------------------------------------------------------------------------
def test_user_write_is_refused_with_the_standard_envelope(client, owner_headers, demo_mode):
    res = client.post(
        "/users", headers=owner_headers,
        json={"name": "Blocked", "email": "blocked@test.dev", "password": "pw12345678"},
    )

    assert res.status_code == 403
    body = res.json()
    # Same envelope shape as every other failure (backend/errors.py) — the
    # middleware writes it by hand, so drift here is a real risk.
    assert body["status_code"] == 403
    assert body["type"] == "Forbidden"
    assert "read-only demo" in body["detail"]
    assert body["extra"]["demo_mode"] is True
    assert set(body) >= {"status_code", "type", "detail", "request_id", "extra"}
    # Still passed through the request-context middleware.
    assert res.headers.get("x-request-id")


def test_device_update_is_refused(client, owner_headers, demo_mode):
    res = client.put("/devices/1", headers=owner_headers, json={"name": "Renamed"})
    assert res.status_code == 403
    assert res.json()["extra"]["demo_mode"] is True


def test_reads_are_untouched(client, owner_headers, demo_mode):
    for path in ("/sightings", "/species", "/devices", "/users/me", "/stats/dashboard"):
        assert client.get(path, headers=owner_headers).status_code == 200, path


def test_login_still_works(client, demo_mode):
    res = client.post(
        "/login", json={"email": "owner@test.dev", "password": OWNER_PASSWORD}
    )
    assert res.status_code == 201
    assert res.json()["access_token"]


def test_device_upload_still_works(client, demo_mode, monkeypatch):
    """The simulator has to keep running — that's what makes the demo live."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_controller.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_controller, "enrich_species", _noop)

    token = asyncio.run(_fresh_device_token())

    res = client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("cap.jpg", b"\xff\xd8\xff\xe0demo-bytes", "image/jpeg")},
        data={
            "timestamp": "2026-07-20T08:15:00+00:00",
            "common_name": "Test Cardinal",
            "scientific_name": "Cardinalis testus",
            "confidence_score": "0.91",
            "classification_tier_used": "gpu",
            "delayed": "false",
        },
    )

    assert res.status_code == 201


# ---------------------------------------------------------------------------
# GET /meta
# ---------------------------------------------------------------------------
def test_meta_is_public_and_reports_normal_mode(client):
    res = client.get("/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["demo_mode"] is False
    # Credentials are never published off a non-demo instance.
    assert "demo_login" not in body


def test_meta_publishes_demo_credentials_in_demo_mode(client, demo_mode):
    body = client.get("/meta").json()
    assert body["demo_mode"] is True
    assert body["demo_login"]["email"] == "dom@peck.deck"
    assert body["demo_login"]["password"] == "peckdeck"


# ---------------------------------------------------------------------------
# Boot-time seeding
# ---------------------------------------------------------------------------
# Seeded into a scratch database rather than the suite's own: the demo dataset
# adds 12 species and 3 devices, which would break the exact-count assertions in
# test_stats/test_species.
async def _seed_scratch(path) -> dict:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as db:
            async with db.begin():
                empty_before = await owner_exists(db)
                total = await seed_demo_data(db)

        async with factory() as db:
            counts = {
                "users": len((await db.execute(select(User))).scalars().all()),
                "species": len((await db.execute(select(Species))).scalars().all()),
                "devices": len((await db.execute(select(Device))).scalars().all()),
                "sightings": len((await db.execute(select(Sighting))).scalars().all()),
            }
            seeded_after = await owner_exists(db)
    finally:
        await engine.dispose()

    return {"empty_before": empty_before, "seeded_after": seeded_after,
            "total": total, **counts}


def test_demo_seed_populates_an_empty_database(tmp_path):
    result = asyncio.run(_seed_scratch(tmp_path / "demo.db"))

    assert result["empty_before"] is False   # nothing there to start with
    assert result["seeded_after"] is True    # ...and the guard now trips
    assert result["users"] == 4
    assert result["species"] == 12
    assert result["devices"] == 3
    # A week of visits — enough for the dashboard, trends and heatmap to read
    # as populated rather than sparse.
    assert result["sightings"] > 100
    assert result["sightings"] == result["total"]


def test_startup_seed_is_inert_when_demo_mode_is_off():
    """`docker compose up` on a normal instance must never invent data."""
    assert settings.DEMO_MODE is False
    asyncio.run(maybe_seed_demo())  # would raise or seed if it did anything
