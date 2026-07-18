"""Pytest fixtures for the backend API.

Runs the real Litestar app against a throwaway file-based SQLite database
(file-based, not :memory:, so the pre-seed connection and the app's own
connection pool share the same data). A small, deterministic dataset is seeded
once per session so the stats endpoints can be asserted exactly.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

# These MUST be set before importing backend.config (Settings reads env at
# import time). A fresh temp file guarantees a clean DB each session.
_TMPDIR = tempfile.mkdtemp(prefix="peckdeck-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long!"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from litestar.testing import TestClient  # noqa: E402

from backend.auth.jwt_utils import create_user_token, hash_password  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database.connection import (  # noqa: E402
    create_tables,
    dispose_db,
    get_session_factory,
    init_db,
)
from backend.database.models import (  # noqa: E402
    Device,
    DeviceUser,
    Sighting,
    Species,
    User,
)
from backend.main import app  # noqa: E402

# Populated during seeding so tests can reference known ids/tokens.
IDS: dict = {}


def _species(common, genus, sp, palette):
    return Species(
        common_name=common, genus=genus, species_name=sp, order_name="Passeriformes",
        wiki_url=f"https://en.wikipedia.org/wiki/{common.replace(' ', '_')}",
        palette=json.dumps(palette), silhouette="songbird", note=f"{common} note.",
    )


async def _seed() -> None:
    init_db(settings.DATABASE_URL)
    await create_tables()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as db:
        async with db.begin():
            owner = User(name="Owner One", email="owner@test.dev",
                         password_hash=hash_password("ownerpw"), phone="+15550001",
                         role="owner", notify_email=True, notify_sms=True)
            viewer = User(name="Viewer Two", email="viewer@test.dev",
                          password_hash=hash_password("viewerpw"), phone=None,
                          role="viewer", notify_email=True, notify_sms=False)
            db.add_all([owner, viewer])
            await db.flush()

            spA = _species("Test Cardinal", "Cardinalis", "testus", ["#b8412c", "#5a1810", "#e5b89c"])
            spB = _species("Test Jay", "Cyanocitta", "testus", ["#3f6e89", "#15263a", "#d4cdb8"])
            spC = _species("Test Wren", "Thryothorus", "testus", ["#a86530", "#52301a", "#e5d4b8"])
            db.add_all([spA, spB, spC])
            await db.flush()

            dev1 = Device(name="Dev One", city="Burlington", state="VT", owner_id=owner.id,
                          classification_tier="auto", feed_type="sunflower", token="dev1-token",
                          battery=0.8, signal="good", last_seen=now)              # online
            dev2 = Device(name="Dev Two", city="Stowe", state="VT", owner_id=owner.id,
                          classification_tier="gpu", feed_type="nyjer", token="dev2-token",
                          battery=0.5, signal="good", last_seen=now - timedelta(minutes=40))  # offline
            dev3 = Device(name="Dev Three", city="Essex", state="VT", owner_id=owner.id,
                          classification_tier="local", feed_type="suet", token="dev3-token",
                          battery=0.15, signal="good", last_seen=now)             # warn (low battery)
            db.add_all([dev1, dev2, dev3])
            await db.flush()

            # viewer can access dev1 only (membership, not ownership)
            db.add(DeviceUser(device_id=dev1.id, user_id=viewer.id))

            def sighting(sp, dev, when, conf, tier):
                return Sighting(species_id=sp.id, device_id=dev.id, datetime=when,
                                confidence_score=conf, classification_tier_used=tier, delayed=False)

            three_days_ago = now - timedelta(days=3)
            db.add_all([
                sighting(spA, dev1, now, 0.95, "gpu"),
                sighting(spA, dev1, now, 0.90, "local"),
                sighting(spA, dev1, now, 0.88, "gpu"),
                sighting(spB, dev1, now, 0.80, "local"),
                sighting(spB, dev1, now, 0.75, "local"),
                sighting(spA, dev2, three_days_ago, 0.70, "cloud"),  # not visible to viewer
            ])

            IDS.update(
                owner_id=owner.id, viewer_id=viewer.id,
                dev1_id=dev1.id, dev2_id=dev2.id, dev3_id=dev3.id,
                spA_id=spA.id, spB_id=spB.id, spC_id=spC.id,
            )
    await dispose_db()


@pytest.fixture(scope="session")
def client():
    asyncio.run(_seed())
    with TestClient(app=app) as c:
        yield c


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def owner_headers(client):  # depends on client so IDS is populated
    return _auth(create_user_token(IDS["owner_id"], "owner"))


@pytest.fixture(scope="session")
def viewer_headers(client):
    return _auth(create_user_token(IDS["viewer_id"], "viewer"))
