import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, DeviceUser, Sighting, User


async def get_device(db: AsyncSession, device_id: int) -> Device | None:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


async def get_devices_for_user(db: AsyncSession, user_id: int) -> list[Device]:
    owned = select(Device.id).where(Device.owner_id == user_id)
    member = select(DeviceUser.device_id).where(DeviceUser.user_id == user_id)
    result = await db.execute(
        select(Device).where(or_(Device.id.in_(owned), Device.id.in_(member)))
    )
    return list(result.scalars().all())


async def create_device(
    db: AsyncSession,
    *,
    name: str,
    city: str | None,
    state: str | None,
    owner_id: int,
    feed_type: str | None,
) -> Device:
    device = Device(
        name=name,
        city=city,
        state=state,
        owner_id=owner_id,
        feed_type=feed_type,
        token=secrets.token_urlsafe(32),
    )
    db.add(device)
    await db.flush()
    return device


async def update_device(
    db: AsyncSession,
    device: Device,
    *,
    name: str | None,
    city: str | None,
    state: str | None,
    feed_type: str | None,
) -> Device:
    if name is not None:
        device.name = name
    if city is not None:
        device.city = city
    if state is not None:
        device.state = state
    if feed_type is not None:
        device.feed_type = feed_type
    await db.flush()
    return device


async def get_sighting_counts(db: AsyncSession, device_id: int) -> dict[str, int]:
    """Today / last-7-days / all-time sighting counts for a device."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    def _count(*conditions):
        return (
            select(func.count())
            .select_from(Sighting)
            .where(Sighting.device_id == device_id, *conditions)
        )

    today = (await db.execute(_count(Sighting.datetime >= day_start))).scalar_one()
    week = (await db.execute(_count(Sighting.datetime >= week_start))).scalar_one()
    all_time = (await db.execute(_count())).scalar_one()
    return {"today": today, "week": week, "all_time": all_time}


# The tier mix covers this many recent hours. Tier 2 counts as down for a feeder
# when at least TIER2_WARN_MIN_MISSES captures in the window got no answer from
# it, and those misses are at least TIER2_WARN_SHARE of the captures that asked
# it. The floor keeps a quiet feeder with two visits from tripping the warning.
TIER_MIX_HOURS = 24
TIER2_WARN_MIN_MISSES = 3
TIER2_WARN_SHARE = 0.2

_MIX_TIERS = ("gpu", "local", "cloud", "none")


def tier2_missed(tier_used: str, trace: list[dict] | None) -> bool | None:
    """Whether a capture asked Tier 2 and got no answer. None if it never asked.

    The trace's Tier 2 entry decides, because the tier that answered does not.
    Under the ``gpu`` order a Tier 2 answer below its bar escalates to Tier 1,
    so a ``local`` sighting can come from a healthy GPU server.
    """
    if trace is None:
        # A Pi build from before the trace. Assume the default gpu order.
        return tier_used in ("local", "none")
    gpu = next((a for a in trace if a.get("tier") == "gpu"), None)
    if gpu is None:
        return None
    if gpu.get("outcome") == "not_run":
        # Tier "none" with nothing run is the Pi's classify queue overflowing,
        # most likely behind Tier 2 timeouts. Otherwise an earlier tier answered.
        return True if tier_used == "none" else None
    return gpu.get("outcome") == "failed"


def summarize_tier_mix(rows: list[tuple[str, list[dict] | None]]) -> dict:
    """Tier counts and the Tier 2 warning from ``(tier_used, tier_trace)`` rows."""
    counts = dict.fromkeys(_MIX_TIERS, 0)
    asked = missed = 0
    for tier_used, trace in rows:
        if tier_used in counts:
            counts[tier_used] += 1
        miss = tier2_missed(tier_used, trace)
        if miss is not None:
            asked += 1
            missed += miss
    warning = missed >= TIER2_WARN_MIN_MISSES and missed >= TIER2_WARN_SHARE * asked
    return {
        "window_hours": TIER_MIX_HOURS,
        **counts,
        "tier2_asked": asked,
        "tier2_missed": missed,
        "tier2_warning": warning,
    }


async def get_tier_mix(db: AsyncSession, device_id: int) -> dict:
    """The device's tier mix over the last ``TIER_MIX_HOURS``."""
    since = datetime.now(timezone.utc) - timedelta(hours=TIER_MIX_HOURS)
    rows = await db.execute(
        select(Sighting.classification_tier_used, Sighting.tier_trace).where(
            Sighting.device_id == device_id, Sighting.datetime >= since
        )
    )
    return summarize_tier_mix([tuple(r) for r in rows.all()])


async def update_device_telemetry(
    db: AsyncSession,
    device: Device,
    *,
    battery: float | None,
    signal: str | None,
    live_url: str | None,
) -> Device:
    if battery is not None:
        device.battery = battery
    if signal is not None:
        device.signal = signal
    # Unlike battery and signal, a missing live_url means "not streaming now".
    device.live_url = live_url
    device.last_seen = datetime.now(timezone.utc)
    await db.flush()
    return device


async def mark_device_seen(db: AsyncSession, device_id: int) -> None:
    """Record that a device just reached the backend.

    A device that uploads is alive, even if it never sends a heartbeat. Without
    this the station read "offline" minutes after it sent a sighting.
    """
    device = await get_device(db, device_id)
    if device is not None:
        device.last_seen = datetime.now(timezone.utc)
        await db.flush()


async def add_device_user(db: AsyncSession, device_id: int, user_id: int) -> None:
    existing = await db.execute(
        select(DeviceUser).where(
            DeviceUser.device_id == device_id, DeviceUser.user_id == user_id
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(DeviceUser(device_id=device_id, user_id=user_id))
        await db.flush()


async def remove_device_user(db: AsyncSession, device_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(DeviceUser).where(
            DeviceUser.device_id == device_id, DeviceUser.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
