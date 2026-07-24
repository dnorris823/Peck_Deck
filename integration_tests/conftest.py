"""Fixtures for the Phase 3 integration + contract suite.

Unlike ``backend/tests`` (which runs against a throwaway SQLite file), this
suite exercises the stack against a **real** ``postgres:16`` database and, for
the contract tests, against **live** HTTP servers (the backend and the GPU
inference server) so the actual client code — including the Raspberry Pi
``aiohttp`` clients — is driven end to end.

The whole suite is gated on ``PECK_TEST_DATABASE_URL`` (an asyncpg URL, e.g.
``postgresql+asyncpg://peck_deck:pw@localhost:5432/peck_deck``). When it is not
set — the default for ``pytest -q`` on a laptop with no database — collection is
skipped entirely. CI and ``scripts/run_integration.sh`` set it after standing
up Postgres.
"""
import os
from urllib.parse import urlsplit

import pytest

PG_URL = os.getenv("PECK_TEST_DATABASE_URL")

# ── Destructive-run guard ────────────────────────────────────────────────────
# This suite DROPS EVERY TABLE before seeding. Pointed at a real database it
# destroys all of it — which is exactly what happened once during Phase 8, when
# PECK_TEST_DATABASE_URL was aimed at the live `peck_deck` database and wiped
# 135 sightings including real Raspberry Pi captures.
#
# So: refuse to run unless the target database name marks itself as disposable.
# Override with PECK_TEST_DB_ALLOW_ANY_NAME=1 only if you are certain.
_SAFE_NAME_MARKERS = ("test", "scratch", "ci", "tmp")


def _assert_disposable(url: str) -> None:
    if os.getenv("PECK_TEST_DB_ALLOW_ANY_NAME") == "1":
        return
    name = urlsplit(url).path.lstrip("/")
    if not any(marker in name.lower() for marker in _SAFE_NAME_MARKERS):
        raise RuntimeError(
            f"Refusing to run the integration suite against database {name!r}.\n"
            "This suite DROPS EVERY TABLE before seeding, so it must only target a\n"
            f"disposable database — name it with one of {_SAFE_NAME_MARKERS} "
            "(e.g. 'peck_deck_test').\n"
            "Set PECK_TEST_DB_ALLOW_ANY_NAME=1 to override if you really mean it."
        )


# No database configured → skip the entire integration suite (don't even import
# the test modules, which pull in the backend app bound to this URL).
if not PG_URL:
    collect_ignore_glob = ["test_*.py"]
else:
    _assert_disposable(PG_URL)

    # Bind the backend to the real Postgres BEFORE importing any backend module
    # (backend.config reads DATABASE_URL at import time).
    os.environ["DATABASE_URL"] = PG_URL
    os.environ.setdefault("JWT_SECRET", "integration-secret-key-at-least-32-bytes!!")

    import asyncio

    from litestar.testing import TestClient

    from backend.auth.jwt_utils import create_user_token
    from backend.config import settings
    from backend.database.connection import (
        create_tables,
        dispose_db,
        drop_tables,
        get_session_factory,
        init_db,
    )
    from backend.fixtures import seed_reference_data
    from backend.main import app

    IDS: dict = {}

    async def _prepare_database() -> dict:
        """Reset the real Postgres DB to a clean, deterministic state and seed."""
        init_db(settings.DATABASE_URL)
        await drop_tables()
        await create_tables()
        async with get_session_factory()() as db:
            async with db.begin():
                ids = await seed_reference_data(db)
        await dispose_db()
        return ids

    @pytest.fixture(scope="session")
    def ids() -> dict:
        result = asyncio.run(_prepare_database())
        IDS.update(result)
        return IDS

    @pytest.fixture(scope="session")
    def client(ids):
        """A Litestar TestClient bound to the seeded Postgres database."""
        with TestClient(app=app) as c:
            yield c

    def _auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture(scope="session")
    def owner_headers(ids):
        return _auth(create_user_token(ids["owner_id"], "owner"))

    @pytest.fixture(scope="session")
    def viewer_headers(ids):
        return _auth(create_user_token(ids["viewer_id"], "viewer"))
