"""The optional retention rule: delete old "Unknown" sightings.

Images live in the database as ``bytea``, so every capture grows the table and
the backup dump. An "Unknown" sighting is one no tier could name. Nobody is
likely to look at it again after a few weeks, so it is the one class of row
worth removing on a timer.

``RETENTION_UNKNOWN_DAYS`` sets the age in days. 0 turns the rule off, and 0 is
the default. When on, the API process runs the rule once at startup and then
every 24 hours. A sighting a person corrected to a real species no longer
points at "Unknown", so the rule never touches it.
"""
import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database.connection import get_session_factory
from .database.models import Sighting, Species

logger = logging.getLogger("peckdeck.retention")

# The species name the Pi sends when every tier failed, and what Tier 3 returns
# for no bird. See raspberry_pi_code/pipeline.py.
UNKNOWN_COMMON_NAME = "Unknown"

RUN_INTERVAL_SECONDS = 24 * 60 * 60

_task: asyncio.Task | None = None


async def delete_old_unknown(
    db: AsyncSession, days: int, *, now: datetime | None = None
) -> int:
    """Delete "Unknown" sightings older than ``days``. Return how many went.

    ``days`` of 0 or less deletes nothing.
    """
    if days <= 0:
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    unknown = select(Species.id).where(Species.common_name == UNKNOWN_COMMON_NAME)
    result = await db.execute(
        delete(Sighting)
        .where(Sighting.species_id.in_(unknown), Sighting.datetime < cutoff)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def run_once(days: int) -> int:
    """Apply the rule in its own session and log the count."""
    async with get_session_factory()() as db:
        async with db.begin():
            deleted = await delete_old_unknown(db, days)
    logger.info(
        "retention: deleted %d Unknown sightings older than %d days", deleted, days
    )
    return deleted


async def _loop(days: int) -> None:
    while True:
        try:
            await run_once(days)
        except Exception:
            # A failed run must not end the loop. Tomorrow's run tries again.
            logger.exception("retention: run failed")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)


def start(days: int) -> None:
    """Start the daily task, or do nothing when the rule is off."""
    global _task
    if days < 0:
        raise RuntimeError(f"RETENTION_UNKNOWN_DAYS must be 0 (off) or more, not {days}")
    if days == 0:
        logger.info("retention: off (RETENTION_UNKNOWN_DAYS is 0)")
        return
    logger.info("retention: on, deleting Unknown sightings older than %d days", days)
    _task = asyncio.create_task(_loop(days))


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
