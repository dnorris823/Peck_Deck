"""Aggregate read queries for the web dashboard.

Everything here is scoped to the devices a user can access, and all bucketing
(heatmap, per-day sparklines) is done in Python rather than with SQL date
functions so the same code works on PostgreSQL (prod) and SQLite (dev/seed).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Sighting, Species
from ..sightings.operations import _accessible_device_ids


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def species_counts(db: AsyncSession, user_id: int) -> list[dict]:
    """Per-species sighting totals + first-seen date, most frequent first."""
    accessible = await _accessible_device_ids(db, user_id)
    if not accessible:
        return []
    rows = await db.execute(
        select(
            Species,
            func.count(Sighting.id).label("count"),
            func.min(Sighting.datetime).label("first_seen"),
        )
        .join(Sighting, Sighting.species_id == Species.id)
        .where(Sighting.device_id.in_(accessible))
        .group_by(Species.id)
    )
    result = []
    for species, count, first_seen in rows.all():
        result.append(
            {
                "species": species,
                "count": count,
                "first_seen": _aware(first_seen).isoformat() if first_seen else None,
            }
        )
    result.sort(key=lambda r: r["count"], reverse=True)
    return result


async def _recent_sightings(
    db: AsyncSession, accessible: list[int], since: datetime
) -> list[Sighting]:
    if not accessible:
        return []
    rows = await db.execute(
        select(Sighting).where(
            Sighting.device_id.in_(accessible), Sighting.datetime >= since
        )
    )
    return list(rows.scalars().all())


async def heatmap(db: AsyncSession, user_id: int) -> list[list[int]]:
    """7×24 grid of sighting counts, rows Mon→Sun, over the last 7 days."""
    accessible = await _accessible_device_ids(db, user_id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    grid = [[0] * 24 for _ in range(7)]
    for s in await _recent_sightings(db, accessible, since):
        dt = _aware(s.datetime)
        grid[dt.weekday()][dt.hour] += 1
    return grid


async def _sightings_in_range(
    db: AsyncSession, accessible: list[int], since: datetime, device_id: int | None = None
) -> list[Sighting]:
    """Sightings since `since`, optionally narrowed to one accessible device."""
    if not accessible:
        return []
    device_ids = accessible if device_id is None else [device_id]
    if device_id is not None and device_id not in accessible:
        return []
    rows = await db.execute(
        select(Sighting).where(
            Sighting.device_id.in_(device_ids), Sighting.datetime >= since
        )
    )
    return list(rows.scalars().all())


def _longest_streak(dates: set) -> int:
    """Longest run of consecutive days that had at least one visit."""
    if not dates:
        return 0
    ordered = sorted(dates)
    longest = current = 1
    for prev, day in zip(ordered, ordered[1:]):
        if (day - prev).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


async def insights(
    db: AsyncSession, user_id: int, *, days: int = 30, device_id: int | None = None
) -> dict:
    """Richer analytics over a selectable window (FLEDGE Phase 6).

    Complements `dashboard()`, which is fixed to 7 days and drives the stat
    tiles. This answers "what's been happening at the feeder?" over a range:
    a visits-per-day trend, which hours are busiest, how species diversity is
    accumulating, what's newly arrived, and the longest run of active days.

    Bucketing is done in Python rather than with SQL date functions, matching
    the rest of this module, so the same code runs on PostgreSQL and SQLite.
    """
    days = max(1, min(days, 365))
    accessible = await _accessible_device_ids(db, user_id)
    now = datetime.now(timezone.utc)
    today = now.date()
    since = (now - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    recent = await _sightings_in_range(db, accessible, since, device_id)

    # ── Visits per day ───────────────────────────────────────────────────────
    per_day_counts = [0] * days
    per_day_species: list[set] = [set() for _ in range(days)]
    hours = [0] * 24
    active_dates: set = set()
    by_device: dict[int, int] = defaultdict(int)

    for s in recent:
        dt = _aware(s.datetime)
        idx = (days - 1) - (today - dt.date()).days
        if 0 <= idx < days:
            per_day_counts[idx] += 1
            per_day_species[idx].add(s.species_id)
        hours[dt.hour] += 1
        active_dates.add(dt.date())
        by_device[s.device_id] += 1

    day_labels = [
        (since.date() + timedelta(days=i)).isoformat() for i in range(days)
    ]

    # ── Cumulative diversity across the window ───────────────────────────────
    diversity: list[int] = []
    seen: set = set()
    for day in per_day_species:
        seen |= day
        diversity.append(len(seen))

    # ── First-seen: which species arrived inside the window ──────────────────
    # A species is "new" only if its all-time first sighting falls in the window,
    # not merely its first sighting within it.
    new_species: list[dict] = []
    if accessible:
        first_rows = await db.execute(
            select(Species, func.min(Sighting.datetime).label("first_seen"))
            .join(Sighting, Sighting.species_id == Species.id)
            .where(Sighting.device_id.in_(accessible))
            .group_by(Species.id)
        )
        for species, first_seen in first_rows.all():
            if first_seen is None:
                continue
            first = _aware(first_seen)
            if first >= since:
                new_species.append(
                    {
                        "id": species.id,
                        "common_name": species.common_name,
                        "first_seen": first.isoformat(),
                    }
                )
        new_species.sort(key=lambda r: r["first_seen"], reverse=True)

    busiest_hour = max(range(24), key=lambda h: hours[h]) if recent else None
    busiest_day_idx = (
        max(range(days), key=lambda i: per_day_counts[i]) if recent else None
    )

    return {
        "days": days,
        "device_id": device_id,
        "total_sightings": len(recent),
        "distinct_species": len(seen),
        "day_labels": day_labels,
        "per_day": per_day_counts,
        "diversity": diversity,
        "hours": hours,
        "busiest_hour": busiest_hour,
        "busiest_day": day_labels[busiest_day_idx] if busiest_day_idx is not None else None,
        "active_days": len(active_dates),
        "longest_streak": _longest_streak(active_dates),
        "new_species": new_species,
        "per_device": [
            {"device_id": did, "count": count}
            for did, count in sorted(by_device.items(), key=lambda kv: -kv[1])
        ],
    }


async def dashboard(db: AsyncSession, user_id: int) -> dict:
    accessible = await _accessible_device_ids(db, user_id)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    recent = await _recent_sightings(db, accessible, week_start)

    today_sightings = sum(1 for s in recent if _aware(s.datetime) >= day_start)
    species_this_week = len({s.species_id for s in recent})
    avg_confidence = (
        round(sum(s.confidence_score for s in recent) / len(recent), 3)
        if recent
        else None
    )

    # Per-day buckets for the last 7 days (index 0 = 6 days ago … 6 = today).
    today = now.date()
    day_counts = [0] * 7
    day_conf_sum = [0.0] * 7
    day_species: list[set] = [set() for _ in range(7)]
    for s in recent:
        idx = 6 - (today - _aware(s.datetime).date()).days
        if 0 <= idx < 7:
            day_counts[idx] += 1
            day_conf_sum[idx] += s.confidence_score
            day_species[idx].add(s.species_id)

    spark_sightings = day_counts
    spark_confidence = [
        round(day_conf_sum[i] / day_counts[i], 3) if day_counts[i] else 0.0
        for i in range(7)
    ]
    # Cumulative distinct species seen through each day.
    spark_species = []
    seen: set = set()
    for day in day_species:
        seen |= day
        spark_species.append(len(seen))

    counts = await species_counts(db, user_id)
    most_frequent = counts[0]["species"].common_name if counts else None
    most_frequent_count = counts[0]["count"] if counts else 0

    return {
        "today_sightings": today_sightings,
        "species_this_week": species_this_week,
        "avg_confidence": avg_confidence,
        "most_frequent": most_frequent,
        "most_frequent_count": most_frequent_count,
        "total_species": len(counts),
        "total_devices": len(accessible),
        "spark_sightings": spark_sightings,
        "spark_species": spark_species,
        "spark_confidence": spark_confidence,
    }
