"""Contract test for the device simulator (FLEDGE Phase 5).

The simulator's entire reason to exist is that it stands in for the Pi *without
being a second implementation of the Pi*: it drives
``raspberry_pi_code.api_client.BackendClient`` unmodified. This test runs the
real CLI (``backend.simulator.main_async``) against a **live** uvicorn backend on
real Postgres and checks what actually landed — the same seam as
``test_contract_pi_backend.py``, one layer up.

If these pass, "verified with the simulator" means the same thing as "verified
with a Pi" for everything downstream of the upload.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.sightings.aftercare as sighting_aftercare
from backend.config import settings
from backend.database.models import Sighting
from backend.fixtures import OWNER_PASSWORD
from backend.main import app
from backend.simulator import TIER_PROFILE, discover_devices, main_async
from integration_tests._dbutil import create_throwaway_device, sightings_for_device
from integration_tests._live import run_server


@pytest.fixture(autouse=True)
def _silence_side_effects(monkeypatch):
    """No outbound calls: the simulator invents species this DB has never seen.

    A real run *should* enrich them from Wikipedia/GBIF — that is the product
    behaviour — but a contract test must not depend on the internet, and the
    fire-and-forget tasks would otherwise still be running as the server shuts
    down.
    """
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _noop)


def _run_cli(base_url: str, token: str, *args: str) -> int:
    return asyncio.run(main_async([
        "--api-url", base_url, "--device-token", token, "--seed", "17", *args,
    ]))


def test_burst_backfills_history_through_the_pi_client(ids):
    token, device_id = create_throwaway_device("sim-burst")

    with run_server(app) as base_url:
        assert _run_cli(base_url, token, "--mode", "burst",
                        "--count", "12", "--days", "5") == 0

    rows = sightings_for_device(device_id)
    assert len(rows) == 12

    for row in rows:
        # Every visit carried a real placeholder JPEG into `bytea`. The gallery
        # and the detail view both depend on that, and an empty upload would
        # still have returned 201 — so assert the bytes, not the status.
        assert row["has_image"] is True
        assert row["image_len"] > 5_000
        tier = row["classification_tier_used"]
        assert tier in TIER_PROFILE
        low, high = TIER_PROFILE[tier][1]
        assert low <= row["confidence_score"] <= high
        # Backdated captures are exactly what the offline-sync path uploads.
        assert row["delayed"] is True


def test_live_mode_posts_current_sightings(ids):
    token, device_id = create_throwaway_device("sim-live")
    before = datetime.now(timezone.utc) - timedelta(minutes=1)

    with run_server(app) as base_url:
        assert _run_cli(base_url, token, "--mode", "live",
                        "--interval", "0.01", "--jitter", "0", "--limit", "3") == 0

    rows = sightings_for_device(device_id)
    assert len(rows) == 3
    assert all(row["delayed"] is False for row in rows)
    assert _latest_sighting_time(device_id) >= before


def test_simulator_discovers_its_own_device_tokens(ids):
    """Zero configuration: sign in, read the tokens off GET /devices, go."""
    with run_server(app) as base_url:
        devices = asyncio.run(
            discover_devices(base_url, "owner@test.dev", OWNER_PASSWORD)
        )

    # The seeded owner owns three stations; each must come back with a token
    # the simulator can authenticate with.
    assert len(devices) >= 3
    for device_id, name, token in devices:
        assert isinstance(device_id, int)
        assert name and token


def test_simulator_keeps_working_while_demo_mode_blocks_user_writes(ids, monkeypatch):
    """The point of the demo-mode carve-out: read-only for people, live for devices.

    ``DEMO_MODE`` is flipped *after* the server has started, so the boot-time
    demo seed doesn't fire against the integration database.
    """
    token, device_id = create_throwaway_device("sim-demo")

    with run_server(app) as base_url:
        monkeypatch.setattr(settings, "DEMO_MODE", True)

        assert _run_cli(base_url, token, "--mode", "live",
                        "--interval", "0.01", "--jitter", "0", "--limit", "2") == 0
        status = _attempt_user_write(base_url, ids["dev1_id"])

    assert len(sightings_for_device(device_id)) == 2
    assert status == 403


# ── helpers ──────────────────────────────────────────────────────────────────
def _with_engine(coro_factory):
    """Run ``coro_factory(session_factory)`` on its own engine and event loop.

    asyncpg binds a connection to the loop that opened it, so these helpers
    can't share the app's engine (see ``_dbutil`` for the same pattern).
    """
    async def _main():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            return await coro_factory(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(_main())


def _latest_sighting_time(device_id: int) -> datetime:
    async def _query(factory):
        async with factory() as db:
            result = await db.execute(
                select(Sighting.datetime)
                .where(Sighting.device_id == device_id)
                .order_by(Sighting.datetime.desc())
                .limit(1)
            )
            return result.scalar_one()

    when = _with_engine(_query)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _attempt_user_write(base_url: str, device_id: int) -> int:
    """Sign in as the owner and try to rename a device; return the HTTP status."""
    async def _attempt() -> int:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as session:
            async with session.post(
                f"{base_url}/login",
                json={"email": "owner@test.dev", "password": OWNER_PASSWORD},
            ) as resp:
                resp.raise_for_status()
                jwt = (await resp.json())["access_token"]
            async with session.put(
                f"{base_url}/devices/{device_id}",
                json={"name": "Renamed By A Reviewer"},
                headers={"Authorization": f"Bearer {jwt}"},
            ) as resp:
                return resp.status

    return asyncio.run(_attempt())
