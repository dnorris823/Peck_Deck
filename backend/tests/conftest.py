"""Pytest fixtures for the backend API.

Runs the real Litestar app against a throwaway file-based SQLite database
(file-based, not :memory:, so the pre-seed connection and the app's own
connection pool share the same data). A small, deterministic dataset is seeded
once per session so the stats endpoints can be asserted exactly.

The dataset itself lives in :mod:`backend.fixtures` so the same seeding code
runs against SQLite here and against a real ``postgres:16`` service in the
integration suite (``integration_tests/``).
"""
import os
import tempfile

# These MUST be set before importing backend.config (Settings reads env at
# import time). A fresh temp file guarantees a clean DB each session.
_TMPDIR = tempfile.mkdtemp(prefix="peckdeck-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long!"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from litestar.testing import TestClient  # noqa: E402

from backend.auth.jwt_utils import create_user_token  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database.connection import (  # noqa: E402
    create_tables,
    dispose_db,
    get_session_factory,
    init_db,
)
from backend.fixtures import seed_reference_data  # noqa: E402
from backend.main import app  # noqa: E402

# Populated during seeding so tests can reference known ids/tokens.
IDS: dict = {}


async def _seed() -> None:
    init_db(settings.DATABASE_URL)
    await create_tables()
    async with get_session_factory()() as db:
        async with db.begin():
            IDS.update(await seed_reference_data(db))
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
