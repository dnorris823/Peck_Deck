"""Dev tools — POST /dev/sighting and the DEV_TOOLS flag that gates it.

Two things worth pinning. First, the gate: the route must be invisible unless
the flag is on, and the flag must be off by default, because this endpoint mints
fictional records on a caller's stations. Second, that a fabricated sighting is a
*real* sighting — same table, same user routes — since a dev button that produced
something the rest of the app treated differently would be worse than no button.

``settings.DEV_TOOLS`` is monkeypatched rather than set in the environment: the
app is built once per session, which is exactly why the handler reads the flag
per request instead of deciding at registration time.

Everything that actually creates a sighting runs as a throwaway owner with a
station of their own. The suite's seeded dataset is asserted by exact count in
test_stats/test_insights/test_export, so a test that added a visit to a shared
device would break five other files.
"""
import asyncio
import secrets

import pytest

import backend.sightings.aftercare as sighting_aftercare
from backend.auth.jwt_utils import create_user_token
from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Device, User


@pytest.fixture
def dev_tools(monkeypatch):
    monkeypatch.setattr(settings, "DEV_TOOLS", True)
    return True


@pytest.fixture(autouse=True)
def _silence_side_effects(monkeypatch):
    """The route schedules the same fire-and-forget tasks as a real upload."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _noop)


async def _make_user_with_device() -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(
                name="Dev Tools Tester",
                email=f"devtools_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="owner",
                notify_email=False, notify_sms=False,
            )
            db.add(user)
            await db.flush()
            db.add(Device(name="Dev Bench", owner_id=user.id,
                          classification_tier="auto", token=secrets.token_urlsafe(12)))
            return user.id


@pytest.fixture(scope="module")
def scratch_user_id(client):  # depends on client so the database exists
    return asyncio.run(_make_user_with_device())


@pytest.fixture
def scratch_headers(scratch_user_id):
    return {"Authorization": f"Bearer {create_user_token(scratch_user_id, 'owner')}"}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def test_dev_tools_is_off_by_default():
    """Nothing in the default environment may unlock this."""
    assert settings.DEV_TOOLS is False


def test_route_404s_when_disabled(client, scratch_headers):
    """A disabled dev tool looks like a route that was never registered."""
    res = client.post("/dev/sighting", headers=scratch_headers, json={})
    assert res.status_code == 404


def test_route_is_absent_from_the_openapi_document(client):
    """It is not part of the Pi/frontend contract, so it stays out of the spec."""
    paths = client.get("/schema/openapi.json").json()["paths"]
    assert "/dev/sighting" not in paths
    # Guard the guard: /devices is a real documented route and also starts
    # with "/dev", so a prefix check here would pass for the wrong reason.
    assert "/devices" in paths


def test_requires_authentication(client, dev_tools):
    assert client.post("/dev/sighting", json={}).status_code == 401


def test_meta_reports_the_flag(client, dev_tools):
    assert client.get("/meta").json()["dev_tools"] is True


def test_meta_reports_the_flag_off_by_default(client):
    assert client.get("/meta").json()["dev_tools"] is False


# ---------------------------------------------------------------------------
# What it creates
# ---------------------------------------------------------------------------
def test_creates_a_real_sighting(client, scratch_headers, dev_tools):
    before = len(client.get("/sightings?limit=100", headers=scratch_headers).json())

    res = client.post("/dev/sighting", headers=scratch_headers, json={})
    assert res.status_code == 201
    body = res.json()

    # Enough for the button to say what turned up.
    assert body["common_name"]
    assert body["scientific_name"]
    assert 0.0 < body["confidence_score"] <= 1.0
    assert body["classification_tier_used"] in {"local", "gpu", "cloud"}

    # It is an ordinary sighting: readable on the user route it did not use.
    fetched = client.get(f"/sightings/{body['id']}", headers=scratch_headers)
    assert fetched.status_code == 200
    assert fetched.json()["device_id"] == body["device_id"]

    after = client.get("/sightings?limit=100", headers=scratch_headers).json()
    assert len(after) == before + 1
    assert after[0]["id"] == body["id"]  # newest first — it is the latest visit


def test_lands_on_a_device_the_caller_can_see(client, scratch_headers, dev_tools):
    """A fabricated visit on someone else's station would be a data leak."""
    visible = {d["id"] for d in client.get("/devices", headers=scratch_headers).json()}
    assert visible, "fixture should have given this user a station"
    body = client.post("/dev/sighting", headers=scratch_headers, json={}).json()
    assert body["device_id"] in visible


def test_species_comes_from_the_catalogue(client, scratch_headers, dev_tools):
    known = {s["common_name"] for s in client.get("/species", headers=scratch_headers).json()}
    body = client.post("/dev/sighting", headers=scratch_headers, json={}).json()
    assert body["common_name"] in known


def test_viewer_role_can_trigger_it(client, scratch_user_id, dev_tools):
    """It is a dev convenience, not an owner-only administrative action."""
    headers = {"Authorization": f"Bearer {create_user_token(scratch_user_id, 'viewer')}"}
    assert client.post("/dev/sighting", headers=headers, json={}).status_code == 201


def test_refused_in_demo_mode(client, scratch_headers, dev_tools, monkeypatch):
    """One shared account plus a write button is not a combination to ship.

    Demo mode's middleware runs on method+path before any guard, and /dev is not
    on its allowlist — so this is really a test that nobody adds it.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    res = client.post("/dev/sighting", headers=scratch_headers, json={})
    assert res.status_code == 403
    assert res.json()["extra"]["demo_mode"] is True
