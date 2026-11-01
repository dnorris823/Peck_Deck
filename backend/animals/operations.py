"""Feeder measures, their effect on animal visits, and the daily animal counts.

The effect of one measure compares animal visits in the 14 days before it
started with the days after, up to 14, or until it ended if sooner. Each count
is divided by the camera-up hours in its window. The hours a feeder was
offline are left out, by the rule the feed alerts use: a ``DeviceOutage`` row
for each time the backend heard nothing for over 30 minutes, and the time since
``last_seen`` while the feeder is offline now. The hours before the feeder's
first sighting are left out too, since its camera was not running yet.

The rate ratio has a 95% interval from the Poisson counts. The log of the ratio
has a standard error of sqrt(1/a + 1/b), where a and b are the two counts. With
a zero count the interval is undefined, and the API returns null for it.

The bird rate over the same two windows comes alongside. If birds dropped by
the same share, the cause was weather or empty feed, not the measure. One
feeder has no control group, so the web app says "after", never "because of".
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, DeviceOutage, FeederMeasure, Sighting, Species
from ..devices.operations import OFFLINE_AFTER, as_utc
from ..species.operations import ANIMAL, BIRD

WINDOW_DAYS = 14
Z_95 = 1.959964

Span = tuple[datetime, datetime]


# ── Measures ──────────────────────────────────────────────────────────────────


async def list_measures(db: AsyncSession, device_id: int) -> list[FeederMeasure]:
    result = await db.execute(
        select(FeederMeasure)
        .where(FeederMeasure.device_id == device_id)
        .order_by(FeederMeasure.started_at, FeederMeasure.id)
    )
    return list(result.scalars())


async def get_measure(db: AsyncSession, device_id: int, measure_id: int) -> FeederMeasure | None:
    measure = await db.get(FeederMeasure, measure_id)
    return measure if measure is not None and measure.device_id == device_id else None


async def create_measure(
    db: AsyncSession, device_id: int, *, name: str, started_at: datetime, note: str | None
) -> FeederMeasure:
    measure = FeederMeasure(device_id=device_id, name=name, started_at=started_at, note=note)
    db.add(measure)
    await db.flush()
    return measure


async def delete_measure(db: AsyncSession, measure: FeederMeasure) -> None:
    await db.delete(measure)
    await db.flush()


async def measures_in_range(
    db: AsyncSession, device_id: int, start: datetime, end: datetime
) -> list[FeederMeasure]:
    """Measures that were in place at some point in ``[start, end)``."""
    result = await db.execute(
        select(FeederMeasure)
        .where(
            FeederMeasure.device_id == device_id,
            FeederMeasure.started_at < end,
            (FeederMeasure.ended_at.is_(None)) | (FeederMeasure.ended_at >= start),
        )
        .order_by(FeederMeasure.started_at, FeederMeasure.id)
    )
    return list(result.scalars())


# ── Camera-up hours ───────────────────────────────────────────────────────────


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def up_hours(start: datetime, end: datetime, *, up_since: datetime | None, down: list[Span]) -> float:
    """Hours in ``[start, end)`` the feeder was up.

    ``up_since`` is the feeder's first sighting, None when it has none.
    ``down`` is the offline spans.
    """
    if up_since is None:
        return 0.0
    start = max(start, up_since)
    if end <= start:
        return 0.0
    seconds = (end - start).total_seconds()
    for s, e in _merge(down):
        overlap = (min(e, end) - max(s, start)).total_seconds()
        if overlap > 0:
            seconds -= overlap
    return max(seconds, 0.0) / 3600


async def offline_spans(db: AsyncSession, device: Device, since: datetime, now: datetime) -> list[Span]:
    """Offline spans that reach past ``since``, the current one included."""
    rows = await db.execute(
        select(DeviceOutage.started_at, DeviceOutage.ended_at).where(
            DeviceOutage.device_id == device.id, DeviceOutage.ended_at > since
        )
    )
    spans = [(as_utc(s), as_utc(e)) for s, e in rows.all()]
    if device.last_seen is not None and now - as_utc(device.last_seen) > OFFLINE_AFTER:
        spans.append((as_utc(device.last_seen), now))
    return spans


async def first_sighting(db: AsyncSession, device_id: int) -> datetime | None:
    value = (
        await db.execute(select(func.min(Sighting.datetime)).where(Sighting.device_id == device_id))
    ).scalar_one()
    return None if value is None else as_utc(value)


# ── The rate ratio ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RateRatio:
    before: int
    after: int
    before_rate: float | None  # visits per camera-up hour
    after_rate: float | None
    ratio: float | None  # after rate / before rate
    low: float | None  # 95% interval for the ratio
    high: float | None


def rate_ratio(before: int, after: int, before_hours: float, after_hours: float) -> RateRatio:
    """The after/before rate ratio, with a 95% interval from the Poisson counts."""
    before_rate = before / before_hours if before_hours > 0 else None
    after_rate = after / after_hours if after_hours > 0 else None
    ratio = low = high = None
    if before_rate and after_rate is not None:
        ratio = after_rate / before_rate
        if before > 0 and after > 0:
            se = math.sqrt(1 / after + 1 / before)
            low = ratio * math.exp(-Z_95 * se)
            high = ratio * math.exp(Z_95 * se)
    return RateRatio(before, after, before_rate, after_rate, ratio, low, high)


@dataclass(frozen=True)
class Effect:
    before_start: datetime
    after_start: datetime
    after_end: datetime
    before_hours: float
    after_hours: float
    # The after window ran its full 14 days, or to the measure's end.
    complete: bool
    groups: dict[str, RateRatio]
    birds: RateRatio


async def _counts(
    db: AsyncSession, device_id: int, start: datetime, end: datetime
) -> tuple[dict[str, int], int]:
    """Animal visits per group, and bird visits, in ``[start, end)``."""
    rows = await db.execute(
        select(Species.kind, Species.animal_group, func.count(Sighting.id))
        .join(Species, Species.id == Sighting.species_id)
        .where(Sighting.device_id == device_id, Sighting.datetime >= start, Sighting.datetime < end)
        .group_by(Species.kind, Species.animal_group)
    )
    groups: dict[str, int] = {}
    birds = 0
    for kind, group, count in rows.all():
        if kind == ANIMAL and group:
            groups[group] = groups.get(group, 0) + count
        elif kind == BIRD:
            birds += count
    return groups, birds


async def measure_effect(
    db: AsyncSession, device: Device, measure: FeederMeasure, now: datetime
) -> Effect:
    started = as_utc(measure.started_at)
    before_start = started - timedelta(days=WINDOW_DAYS)
    full_end = started + timedelta(days=WINDOW_DAYS)
    if measure.ended_at is not None:
        full_end = min(full_end, as_utc(measure.ended_at))
    after_end = max(min(full_end, now), started)

    down = await offline_spans(db, device, before_start, now)
    up_since = await first_sighting(db, device.id)
    before_hours = up_hours(before_start, started, up_since=up_since, down=down)
    after_hours = up_hours(started, after_end, up_since=up_since, down=down)

    groups_before, birds_before = await _counts(db, device.id, before_start, started)
    groups_after, birds_after = await _counts(db, device.id, started, after_end)
    groups = {
        g: rate_ratio(groups_before.get(g, 0), groups_after.get(g, 0), before_hours, after_hours)
        for g in sorted(set(groups_before) | set(groups_after))
    }
    return Effect(
        before_start=before_start,
        after_start=started,
        after_end=after_end,
        before_hours=before_hours,
        after_hours=after_hours,
        complete=now >= full_end,
        groups=groups,
        birds=rate_ratio(birds_before, birds_after, before_hours, after_hours),
    )


# ── Daily counts ──────────────────────────────────────────────────────────────


def day_bounds(first: date, last: date, tz: str) -> tuple[datetime, datetime]:
    """UTC bounds of local days ``first`` to ``last``, inclusive."""
    zone = ZoneInfo(tz)
    start = datetime.combine(first, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(last + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return start, end


async def daily_counts(
    db: AsyncSession, device_id: int, first: date, last: date, tz: str
) -> list[dict]:
    """One row per local day: animal visits per group, and bird visits."""
    start, end = day_bounds(first, last, tz)
    zone = ZoneInfo(tz)
    rows = await db.execute(
        select(Sighting.datetime, Species.kind, Species.animal_group)
        .join(Species, Species.id == Sighting.species_id)
        .where(Sighting.device_id == device_id, Sighting.datetime >= start, Sighting.datetime < end)
    )
    days = {first + timedelta(days=i): {"animals": {}, "birds": 0}
            for i in range((last - first).days + 1)}
    for when, kind, group in rows.all():
        day = days.get(as_utc(when).astimezone(zone).date())
        if day is None:
            continue
        if kind == ANIMAL and group:
            day["animals"][group] = day["animals"].get(group, 0) + 1
        elif kind == BIRD:
            day["birds"] += 1
    return [{"date": d.isoformat(), **v} for d, v in days.items()]
