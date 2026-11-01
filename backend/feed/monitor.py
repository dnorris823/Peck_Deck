"""The hourly feed check: tell the owner when a feeder runs low or out.

Each run checks every feeder in its own session. Two signals can raise an alert:

- The visit drop. Recent visits far below what the feeder usually gets in the
  same 3 hours of the day. It opens an "out" spell. See ``rules.py``.
- The refill forecast. Visits since the last refill near what one fill
  usually lasts. It opens a "low" spell, at most once per fill.

The visit drop does not run when it cannot trust a quiet feeder:

- the feeder is offline, or came back from an outage in the last 3 hours,
- the camera trigger has not reported an analysis tick in 10 minutes,
- the owner refilled it and visits have not looked normal since.

An out spell ends at the next refill, or when visits are back to half of E.
A low spell ends at the next refill, or turns into an out spell. The owner
gets one alert when a spell opens, and none while it lasts.

``FEED_ALERTS_ENABLED`` turns the task on. It follows ``backend/retention.py``:
one run at startup, then one every hour.
"""
import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_session_factory
from ..database.models import Device, FeedSpell
from ..devices.operations import OFFLINE_AFTER, as_utc
from ..notifications.service import send_feed_alert
from . import operations as ops
from .rules import BASELINE_DAYS, WINDOW, VisitCheck, forecast_low, low_line, out_line, visit_check

logger = logging.getLogger("peckdeck.feed")

RUN_INTERVAL_SECONDS = 60 * 60
# A trigger tick older than this means the trigger thread stopped analysing.
TRIGGER_STALE_AFTER = timedelta(minutes=10)
# After an outage the check waits this long, so the gap is out of the window.
OUTAGE_SETTLE = timedelta(hours=3)

_task: asyncio.Task | None = None


@dataclass(frozen=True)
class FeedAlert:
    device_id: int
    device_name: str
    state: str  # low|out
    line: str

    @property
    def title(self) -> str:
        return f"Feed may be {self.state} at {self.device_name}"


def skip_reason(device: Device, now: datetime) -> str | None:
    """Why the visit drop cannot run now, or None when it can."""
    if device.last_seen is None or now - as_utc(device.last_seen) > OFFLINE_AFTER:
        return "offline"
    if device.trigger_tick_at is None or now - as_utc(device.trigger_tick_at) > TRIGGER_STALE_AFTER:
        return "trigger stale"
    return None


async def _visit_check(db: AsyncSession, device: Device, now: datetime) -> VisitCheck | None:
    reason = skip_reason(device, now)
    if reason is not None:
        logger.debug("feed: device %d skipped, %s", device.id, reason)
        return None
    since = now - timedelta(days=BASELINE_DAYS) - WINDOW
    outages = await ops.outages_since(db, device.id, since)
    if any(end > now - OUTAGE_SETTLE for _, end in outages):
        logger.debug("feed: device %d skipped, back from an outage", device.id)
        return None
    excluded = outages + await ops.out_spells_since(db, device.id, since, now)
    return visit_check(
        await ops.visit_times(db, device.id, since),
        now,
        history_start=await ops.first_visit(db, device.id),
        excluded=excluded,
    )


async def check_device(db: AsyncSession, device: Device, now: datetime) -> FeedAlert | None:
    """Run both rules for one feeder. Return the alert to send, if any."""
    spell = await ops.get_open_spell(db, device.id)
    check = await _visit_check(db, device, now)

    if check is not None and check.normal:
        device.feed_drop_armed = True
        if spell is not None and spell.state == "out":
            logger.info("feed: device %d visits back to normal (%d of %.1f)",
                        device.id, check.observed, check.expected)
            spell.ended_at = now
            spell = None

    if (
        check is not None
        and check.dropped
        and device.feed_drop_armed
        and (spell is None or spell.state == "low")
    ):
        if spell is not None:
            spell.ended_at = now
        db.add(FeedSpell(device_id=device.id, state="out", started_at=now))
        await db.flush()
        logger.info("feed: device %d may be out (%d visits, expected %.1f)",
                    device.id, check.observed, check.expected)
        line = out_line(await ops.last_visit(db, device.id), now)
        return FeedAlert(device.id, device.name, "out", line)

    if spell is None:
        forecast = await ops.fill_forecast(db, device.id)
        if forecast is not None:
            refill, since, per_fill = forecast
            if forecast_low(per_fill, since) and not await ops.low_spell_since(
                db, device.id, as_utc(refill.refilled_at)
            ):
                db.add(FeedSpell(device_id=device.id, state="low", started_at=now))
                await db.flush()
                logger.info("feed: device %d may be low (%d of %.0f visits)",
                            device.id, since, per_fill)
                return FeedAlert(device.id, device.name, "low", low_line(since, per_fill))

    await db.flush()
    return None


async def run_once(now: datetime | None = None) -> list[FeedAlert]:
    """Check every feeder, then send the alerts. Return what was sent."""
    now = now or datetime.now(timezone.utc)
    async with get_session_factory()() as db:
        device_ids = list((await db.execute(select(Device.id))).scalars())
    alerts = []
    for device_id in device_ids:
        try:
            async with get_session_factory()() as db:
                async with db.begin():
                    device = await db.get(Device, device_id)
                    if device is None:
                        continue
                    alert = await check_device(db, device, now)
        except Exception:
            # One feeder's failure must not stop the check for the others.
            logger.exception("feed: check failed for device %d", device_id)
            continue
        if alert is not None:
            alerts.append(alert)
    # After the commits, so a failed send never rolls back a spell.
    for alert in alerts:
        await send_feed_alert(alert.device_id, alert.title, alert.line)
    return alerts


async def _loop() -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("feed: run failed")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)


def start(enabled: bool) -> None:
    global _task
    if not enabled:
        logger.info("feed: alerts off (FEED_ALERTS_ENABLED is false)")
        return
    logger.info("feed: alerts on, checking every feeder each hour")
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
