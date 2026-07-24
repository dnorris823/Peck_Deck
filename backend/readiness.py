"""Liveness and readiness checks.

``/health`` answers "is this process up?" — it must stay cheap and dependency-free
so an orchestrator's liveness probe never restarts a healthy container just
because the database blipped.

``/ready`` answers "can this process actually serve traffic?" — it verifies the
database is reachable *and* that the schema is migrated to the revision this
build expects. A container that is up but pointed at an unmigrated database
should be kept out of the load balancer, not restarted.
"""
import logging
from pathlib import Path

from sqlalchemy import text

from .database.connection import get_session_factory

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "versions"


def expected_revisions() -> set[str]:
    """Revision ids present in this build, read from the migration filenames.

    Parsed from the files rather than by importing Alembic's ScriptDirectory so
    the probe stays fast and has no import-time dependency on alembic being
    configured.
    """
    revisions: set[str] = set()
    if not _MIGRATIONS_DIR.is_dir():
        return revisions

    for path in _MIGRATIONS_DIR.glob("*.py"):
        if path.name.startswith("__"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("revision:") or stripped.startswith("revision ="):
                # e.g.  revision: str = '25d65b9ab024'
                if "=" in stripped:
                    value = stripped.split("=", 1)[1].strip().strip("'\"")
                    if value:
                        revisions.add(value)
                break
    return revisions


async def check_readiness() -> tuple[bool, dict]:
    """Return ``(ready, detail)`` describing database and migration state."""
    detail: dict = {"database": "unknown", "migrations": "unknown"}

    try:
        async with get_session_factory()() as db:
            db_revision = (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    except Exception as exc:
        # Covers both "database unreachable" and "alembic_version missing",
        # i.e. a database that has never been migrated.
        logger.warning("Readiness check failed: %s", exc)
        detail["database"] = "unreachable"
        detail["migrations"] = "unknown"
        detail["error"] = type(exc).__name__
        return False, detail

    detail["database"] = "ok"

    known = expected_revisions()
    detail["applied_revision"] = db_revision

    if db_revision is None:
        detail["migrations"] = "not_applied"
        return False, detail

    if known and db_revision not in known:
        # The database is on a revision this build has never heard of — usually
        # a rollback to an older image against a newer database.
        detail["migrations"] = "unknown_revision"
        return False, detail

    detail["migrations"] = "ok"
    return True, detail
