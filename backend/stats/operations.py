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
