"""Migrations must build the real schema, and must not drift from the models.

The unit and integration suites both create their schema with
``Base.metadata.create_all()`` for speed, which means nothing else in the test
tree would notice if a migration were missing or wrong. These tests close that
gap by running the migrations for real against a scratch Postgres database.

Requires ``PECK_TEST_DATABASE_URL`` (see conftest).
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "backend" / "alembic.ini"

PG_URL = os.environ["PECK_TEST_DATABASE_URL"]
SCRATCH_DB = "peck_deck_migration_test"

EXPECTED_TABLES = {
    "users",
    "user_preferences",
    "devices",
    "device_users",
    "species",
    "sightings",
}


def _url_for(database: str) -> str:
    """Point the configured asyncpg URL at a different database."""
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


async def _admin_exec(statement: str) -> None:
    """Run a CREATE/DROP DATABASE, which cannot execute inside a transaction."""
    engine = create_async_engine(_url_for("postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text(statement))
    finally:
        await engine.dispose()


async def _table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return set(
                await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
            )
    finally:
        await engine.dispose()


def _run_alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch_db():
    """A freshly created, empty database that migrations can be replayed into."""
    asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))
    asyncio.run(_admin_exec(f'CREATE DATABASE "{SCRATCH_DB}"'))
    try:
        yield _url_for(SCRATCH_DB)
    finally:
        asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))


def test_migrations_build_the_full_schema(scratch_db):
    result = _run_alembic("upgrade", "head", database_url=scratch_db)
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"

    found = asyncio.run(_table_names(scratch_db))

    missing = EXPECTED_TABLES - found
    assert not missing, f"migrations did not create: {sorted(missing)}"
    assert "alembic_version" in found, "migration bookkeeping table missing"


def test_migrations_match_the_models(scratch_db):
    """`alembic check` fails if the models have drifted from the migrations.

    This is the guard that makes it safe for the suites to use `create_all()`:
    if someone edits a model without generating a migration, this goes red.
    """
    assert _run_alembic("upgrade", "head", database_url=scratch_db).returncode == 0

    result = _run_alembic("check", database_url=scratch_db)
    assert result.returncode == 0, (
        "models have drifted from migrations — generate one with:\n"
        "  scripts/migrate.sh revision --autogenerate -m 'describe change'\n\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_downgrade_reverses_the_baseline(scratch_db):
    assert _run_alembic("upgrade", "head", database_url=scratch_db).returncode == 0

    result = _run_alembic("downgrade", "base", database_url=scratch_db)
    assert result.returncode == 0, f"downgrade failed:\n{result.stderr}"

    remaining = asyncio.run(_table_names(scratch_db)) - {"alembic_version"}
    assert not remaining, f"downgrade left tables behind: {sorted(remaining)}"
