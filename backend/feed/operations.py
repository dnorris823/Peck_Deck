"""Feed state reads and writes: refills, spells, and the counts the rules need."""
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, DeviceOutage, FeederRefill, FeedSpell, Sighting
from ..devices.operations import as_utc
from .rules import FORECAST_MAX_FILLS, Span, visits_per_fill


async def get_open_spell(db: AsyncSession, device_id: int) -> FeedSpell | None:
    result = await db.execute(
        select(FeedSpell)
        .where(FeedSpell.device_id == device_id, FeedSpell.ended_at.is_(None))
        .order_by(FeedSpell.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def close_open_spells(db: AsyncSession, device_id: int, now: datetime) -> None:
    result = await db.execute(
        select(FeedSpell).where(FeedSpell.device_id == device_id, FeedSpell.ended_at.is_(None))
    )
    for spell in result.scalars():
        spell.ended_at = now


async def log_refill(db: AsyncSession, device: Device, user_id: int, now: datetime) -> FeederRefill:
    """Record a refill. It ends any low or out spell.

    It also disarms the visit-drop rule until visits look normal again. Birds
    that left an empty feeder can take days to come back, and that quiet is
    not empty feed.
    """
    refill = FeederRefill(
        device_id=device.id, refilled_at=now, feed_type=device.feed_type, user_id=user_id
    )
    db.add(refill)
    await close_open_spells(db, device.id, now)
    device.feed_drop_armed = False
    await db.flush()
    return refill


async def get_refills(db: AsyncSession, device_id: int) -> list[FeederRefill]:
    result = await db.execute(
        select(FeederRefill)
        .where(FeederRefill.device_id == device_id)
        .order_by(FeederRefill.refilled_at)
    )
    return list(result.scalars().all())


async def count_visits(
    db: AsyncSession, device_id: int, start: datetime, end: datetime | None = None
) -> int:
    """Sightings of any tier in ``[start, end)``. "Unknown" captures count too."""
    conditions = [Sighting.device_id == device_id, Sighting.datetime >= start]
    if end is not None:
        conditions.append(Sighting.datetime < end)
    return (await db.execute(select(func.count()).select_from(Sighting).where(*conditions))).scalar_one()


async def visit_times(db: AsyncSession, device_id: int, since: datetime) -> list[datetime]:
    result = await db.execute(
        select(Sighting.datetime)
        .where(Sighting.device_id == device_id, Sighting.datetime >= since)
        .order_by(Sighting.datetime)
    )
    return [as_utc(t) for t in result.scalars()]


async def first_visit(db: AsyncSession, device_id: int) -> datetime | None:
    value = (
        await db.execute(select(func.min(Sighting.datetime)).where(Sighting.device_id == device_id))
    ).scalar_one()
    return None if value is None else as_utc(value)


async def last_visit(db: AsyncSession, device_id: int) -> datetime | None:
    value = (
        await db.execute(select(func.max(Sighting.datetime)).where(Sighting.device_id == device_id))
    ).scalar_one()
    return None if value is None else as_utc(value)


async def outages_since(db: AsyncSession, device_id: int, since: datetime) -> list[Span]:
    result = await db.execute(
        select(DeviceOutage.started_at, DeviceOutage.ended_at).where(
            DeviceOutage.device_id == device_id, DeviceOutage.ended_at > since
        )
    )
    return [(as_utc(s), as_utc(e)) for s, e in result.all()]


async def out_spells_since(
    db: AsyncSession, device_id: int, since: datetime, now: datetime
) -> list[Span]:
    """Out spells that reach past ``since``. An open spell runs to ``now``."""
    result = await db.execute(
        select(FeedSpell.started_at, FeedSpell.ended_at).where(
            FeedSpell.device_id == device_id,
            FeedSpell.state == "out",
            or_(FeedSpell.ended_at.is_(None), FeedSpell.ended_at > since),
        )
    )
    return [(as_utc(s), now if e is None else as_utc(e)) for s, e in result.all()]


async def low_spell_since(db: AsyncSession, device_id: int, since: datetime) -> bool:
    """Whether a low spell started at or after ``since``. One warning per fill."""
    result = await db.execute(
        select(FeedSpell.id)
        .where(
            FeedSpell.device_id == device_id,
            FeedSpell.state == "low",
            FeedSpell.started_at >= since,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def fill_forecast(
    db: AsyncSession, device_id: int
) -> tuple[FeederRefill, int, float | None] | None:
    """The last refill, visits since it, and the median visits per fill.

    None before any refill. The median counts only fills of the last refill's
    feed type, and None stands in for it until there are enough of them.
    """
    refills = await get_refills(db, device_id)
    if not refills:
        return None
    last = refills[-1]
    counts = []
    pairs = list(zip(refills, refills[1:]))
    for start, end in reversed(pairs):
        if len(counts) == FORECAST_MAX_FILLS:
            break
        if start.feed_type != last.feed_type:
            continue
        counts.append(await count_visits(db, device_id, start.refilled_at, end.refilled_at))
    since = await count_visits(db, device_id, last.refilled_at)
    return last, since, visits_per_fill(counts)


async def get_feed_status(db: AsyncSession, device_id: int) -> dict:
    """The feeder's feed state for ``GET /devices``, with the time it changed."""
    spell = await get_open_spell(db, device_id)
    last_refill = (
        await db.execute(
            select(func.max(FeederRefill.refilled_at)).where(FeederRefill.device_id == device_id)
        )
    ).scalar_one()
    last_refill = None if last_refill is None else as_utc(last_refill)
    if spell is not None:
        state, changed = spell.state, as_utc(spell.started_at)
    else:
        last_end = (
            await db.execute(
                select(func.max(FeedSpell.ended_at)).where(FeedSpell.device_id == device_id)
            )
        ).scalar_one()
        moments = [t for t in (last_refill, last_end and as_utc(last_end)) if t is not None]
        state, changed = "ok", max(moments) if moments else None
    seen = await last_visit(db, device_id)
    return {
        "state": state,
        "changed_at": changed.isoformat() if changed else None,
        "last_refill_at": last_refill.isoformat() if last_refill else None,
        "last_visit_at": seen.isoformat() if seen else None,
    }
