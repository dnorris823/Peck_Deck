"""Aggregate read queries for the web dashboard.

Everything here is scoped to the devices a user can access. The heatmap and the
per-day sparklines bucket in Python, in UTC, so the same code works on
PostgreSQL (prod) and SQLite (dev/seed).

The local-hour stats are different. They bucket in the viewer's time zone,
because a visit at 19:00 in California is hour 19 to the person looking, not
hour 2. On PostgreSQL the database converts with ``AT TIME ZONE``. SQLite has no
time zone support, so the unit tests take a Python path with the same output.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Integer, Time, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, Sighting, Species
from ..sightings.operations import _accessible_device_ids
from ..species.operations import BIRD, is_bird_sighting


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def parse_zone(tz: str) -> str:
    """Return ``tz`` if it is an IANA zone name, else raise ``ValueError``.

    The name goes to Postgres as a bound parameter, so this check gives a clear
    400 rather than guarding against injection. ZoneInfo also rejects path-like
    keys.
    """
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {tz!r}") from None
    return tz


async def _scoped_device_ids(
    db: AsyncSession, user_id: int, device_id: int | None
) -> list[int]:
    """The user's devices, or only ``device_id`` when given.

    A ``device_id`` the user cannot see scopes to nothing, as on ``GET /sightings``.
    """
    accessible = await _accessible_device_ids(db, user_id)
    if device_id is None:
        return accessible
    return [d for d in accessible if d == device_id]


# How many days of history feed the species list's ``peak_hours``.
PEAK_WINDOW_DAYS = 30


async def _local_hour_rows(
    db: AsyncSession,
    accessible: list[int],
    tz: str,
    *,
    since: datetime | None,
    species_id: int | None = None,
) -> list[tuple[int, int, int, time, time]]:
    """Visits grouped by species and local hour in ``tz``.

    Each row is ``(species_id, hour, count, earliest, latest)``. ``earliest`` and
    ``latest`` are the local times of day of the first and last visit in that
    hour. ``since`` of None means all time. Without ``species_id`` it counts
    birds only, so a squirrel never makes a busy hour.
    """
    if not accessible:
        return []
    filters = [Sighting.device_id.in_(accessible)]
    if since is not None:
        filters.append(Sighting.datetime >= since)
    if species_id is not None:
        filters.append(Sighting.species_id == species_id)
    else:
        filters.append(is_bird_sighting())

    if db.bind.dialect.name == "postgresql":
        local = Sighting.datetime.op("AT TIME ZONE")(tz)
        hour = cast(func.extract("hour", local), Integer).label("hour")
        rows = await db.execute(
            select(
                Sighting.species_id,
                hour,
                func.count(Sighting.id),
                func.min(cast(local, Time)),
                func.max(cast(local, Time)),
            )
            .where(*filters)
            .group_by(Sighting.species_id, hour)
        )
        return [tuple(r) for r in rows.all()]

    # SQLite has no AT TIME ZONE, so convert in Python. The rows come out the same.
    zone = ZoneInfo(tz)
    rows = await db.execute(select(Sighting.species_id, Sighting.datetime).where(*filters))
    groups: dict[tuple[int, int], list[time]] = {}
    for sp_id, when in rows.all():
        local_dt = _aware(when).astimezone(zone)
        groups.setdefault((sp_id, local_dt.hour), []).append(local_dt.time())
    return [
        (sp_id, hour, len(times), min(times), max(times))
        for (sp_id, hour), times in groups.items()
    ]


def peak_hours(counts: list[int], limit: int = 2) -> list[int]:
    """The busiest local hours as distinct peaks, busiest first.

    An hour is a peak when it beats the hour before it and the hour after it
    does not beat it, wrapping at midnight. So a busy 8 and 9 am count as one
    peak, at 8, and a second peak has to be a separate bump in the day. A day
    with no bump at all falls back to its first busiest hour.
    """
    peaks = [
        h
        for h in range(24)
        if counts[h] > counts[h - 1] and counts[h] >= counts[(h + 1) % 24]
    ]
    if not peaks and any(counts):
        peaks = [counts.index(max(counts))]
    peaks.sort(key=lambda h: (-counts[h], h))
    return peaks[:limit]


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t is not None else None


async def hours(
    db: AsyncSession,
    user_id: int,
    *,
    tz: str,
    days: int | None,
    species_id: int | None = None,
    device_id: int | None = None,
) -> dict:
    """Visit counts per local hour in ``tz``, for the species dial.

    ``days`` of None means all time. ``species_id`` of None covers every species.
    ``device_id`` of None covers every feeder the user can see.
    """
    accessible = await _scoped_device_ids(db, user_id, device_id)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    rows = await _local_hour_rows(db, accessible, tz, since=since, species_id=species_id)

    counts = [0] * 24
    earliest: time | None = None
    latest: time | None = None
    for _sp, hour, count, first, last in rows:
        counts[hour] += count
        earliest = first if earliest is None else min(earliest, first)
        latest = last if latest is None else max(latest, last)
    return {
        "counts": counts,
        "total": sum(counts),
        "peak_hours": peak_hours(counts),
        "earliest": _hhmm(earliest),
        "latest": _hhmm(latest),
    }


def _utc(dt: datetime) -> datetime:
    """``dt`` in UTC, with a naive value read as UTC.

    SQLite stores the wall clock without its offset, so a bound parameter has
    to be in UTC to compare against it.
    """
    return _aware(dt).astimezone(timezone.utc)


async def species_counts(
    db: AsyncSession,
    user_id: int,
    tz: str | None = None,
    *,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    device_id: int | None = None,
) -> list[dict]:
    """Per-species totals with first and last seen, most frequent first.

    With ``tz``, each row also has ``peak_hours`` in local hours over the last
    30 days. Without it, ``peak_hours`` is None.

    ``from_date`` and ``to_date`` are inclusive, as on ``GET /sightings``. With
    either, ``count``, ``first_seen`` and ``last_seen`` cover only that range,
    and a species with no visit in it is left out. ``peak_hours`` keeps its
    30-day window.

    With ``device_id``, everything covers that one feeder.

    Birds only. Animal visits are not species in this sense.
    """
    accessible = await _scoped_device_ids(db, user_id, device_id)
    if not accessible:
        return []
    filters = [Sighting.device_id.in_(accessible), Species.kind == BIRD]
    if from_date is not None:
        filters.append(Sighting.datetime >= _utc(from_date))
    if to_date is not None:
        filters.append(Sighting.datetime <= _utc(to_date))
    rows = await db.execute(
        select(
            Species,
            func.count(Sighting.id).label("count"),
            func.min(Sighting.datetime).label("first_seen"),
            func.max(Sighting.datetime).label("last_seen"),
        )
        .join(Sighting, Sighting.species_id == Species.id)
        .where(*filters)
        .group_by(Species.id)
    )

    by_species: dict[int, list[int]] = {}
    if tz is not None:
        since = datetime.now(timezone.utc) - timedelta(days=PEAK_WINDOW_DAYS)
        for sp_id, hour, count, _first, _last in await _local_hour_rows(
            db, accessible, tz, since=since
        ):
            by_species.setdefault(sp_id, [0] * 24)[hour] += count

    result = []
    for species, count, first_seen, last_seen in rows.all():
        result.append(
            {
                "species": species,
                "count": count,
                "first_seen": _aware(first_seen).isoformat() if first_seen else None,
                "last_seen": _aware(last_seen).isoformat() if last_seen else None,
                "peak_hours": (
                    peak_hours(by_species.get(species.id, [0] * 24))
                    if tz is not None
                    else None
                ),
            }
        )
    result.sort(key=lambda r: r["count"], reverse=True)
    return result


def _names_a_species():
    """A WHERE clause that drops "Unknown", the species the Pi files when no tier names one."""
    unknown = select(Species.id).where(func.lower(func.trim(Species.common_name)) == "unknown")
    return Sighting.species_id.not_in(unknown)


def _year_bounds(year: int, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """1 January of ``year`` to 1 January of the next, local midnight, in UTC."""
    start = datetime(year, 1, 1, tzinfo=zone)
    end = datetime(year + 1, 1, 1, tzinfo=zone)
    return _utc(start), _utc(end)


async def life_list(
    db: AsyncSession,
    user_id: int,
    *,
    tz: str,
    year: int | None = None,
    device_id: int | None = None,
) -> dict:
    """Every bird species recorded, with its first sighting, for one year or all time.

    ``year`` of None is the life list. A year is the year list, bounded by local
    midnight on 1 January in ``tz``. Each row is a ``species_counts`` row for the
    range, plus the feeder of its first sighting in the range, and
    ``new_in_year``. That is True when the species' first sighting ever, in this
    scope, falls in ``year``, or in the current local year for the life list.

    ``years`` lists every local year with a bird sighting, newest first, for the
    year picker. With ``device_id``, everything covers that one feeder.

    Birds only, through ``is_bird_sighting()``, and never "Unknown".
    """
    zone = ZoneInfo(tz)
    accessible = await _scoped_device_ids(db, user_id, device_id)
    result = {"year": year, "years": [], "species": []}
    if not accessible:
        return result
    named_birds = [Sighting.device_id.in_(accessible), is_bird_sighting(), _names_a_species()]

    first_ever: dict[int, datetime] = {
        sp_id: _aware(when)
        for sp_id, when in (
            await db.execute(
                select(Sighting.species_id, func.min(Sighting.datetime))
                .where(*named_birds)
                .group_by(Sighting.species_id)
            )
        ).all()
    }
    if not first_ever:
        return result

    # Few years per feeder, so one cheap EXISTS per candidate year beats a
    # time zone conversion that differs between Postgres and SQLite.
    span = (
        await db.execute(select(func.min(Sighting.datetime), func.max(Sighting.datetime)).where(*named_birds))
    ).one()
    first_year = _aware(span[0]).astimezone(zone).year
    last_year = _aware(span[1]).astimezone(zone).year
    for y in range(last_year, first_year - 1, -1):
        lo, hi = _year_bounds(y, zone)
        hit = await db.execute(
            select(Sighting.id).where(*named_birds, Sighting.datetime >= lo, Sighting.datetime < hi).limit(1)
        )
        if hit.first() is not None:
            result["years"].append(y)

    in_range = list(named_birds)
    start = end = None
    if year is not None:
        start, end = _year_bounds(year, zone)
        in_range += [Sighting.datetime >= start, Sighting.datetime < end]
    new_lo, new_hi = _year_bounds(year if year is not None else datetime.now(zone).year, zone)

    # The feeder of each species' first sighting in range. Ties on the
    # timestamp go to the lower sighting id, so the answer is stable.
    rank = (
        func.row_number()
        .over(partition_by=Sighting.species_id, order_by=(Sighting.datetime, Sighting.id))
        .label("rank")
    )
    firsts = select(Sighting.species_id, Sighting.device_id, rank).where(*in_range).subquery()
    first_feeder = {
        sp_id: (dev_id, name)
        for sp_id, dev_id, name in (
            await db.execute(
                select(firsts.c.species_id, Device.id, Device.name)
                .join(Device, Device.id == firsts.c.device_id)
                .where(firsts.c.rank == 1)
            )
        ).all()
    }

    rows = await species_counts(
        db,
        user_id,
        tz,
        from_date=start,
        # species_counts takes an inclusive bound, so stop just short of 1 January.
        to_date=end - timedelta(microseconds=1) if end is not None else None,
        device_id=device_id,
    )
    for row in rows:
        sp_id = row["species"].id
        if sp_id not in first_feeder:
            continue  # "Unknown", which species_counts keeps for the Species page
        row["first_feeder_id"], row["first_feeder_name"] = first_feeder[sp_id]
        row["new_in_year"] = new_lo <= first_ever[sp_id] < new_hi
        result["species"].append(row)
    result["species"].sort(key=lambda r: datetime.fromisoformat(r["first_seen"]), reverse=True)
    return result


async def _recent_sightings(
    db: AsyncSession, accessible: list[int], since: datetime
) -> list[Sighting]:
    if not accessible:
        return []
    rows = await db.execute(
        select(Sighting).where(
            Sighting.device_id.in_(accessible),
            Sighting.datetime >= since,
            is_bird_sighting(),
        )
    )
    return list(rows.scalars().all())


async def heatmap(
    db: AsyncSession, user_id: int, device_id: int | None = None
) -> list[list[int]]:
    """7×24 grid of bird sighting counts, rows Mon→Sun, over the last 7 days."""
    accessible = await _scoped_device_ids(db, user_id, device_id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    grid = [[0] * 24 for _ in range(7)]
    for s in await _recent_sightings(db, accessible, since):
        dt = _aware(s.datetime)
        grid[dt.weekday()][dt.hour] += 1
    return grid


async def dashboard(db: AsyncSession, user_id: int, device_id: int | None = None) -> dict:
    accessible = await _scoped_device_ids(db, user_id, device_id)
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

    counts = await species_counts(db, user_id, device_id=device_id)
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


async def storage(db: AsyncSession) -> dict:
    """Bytes on disk for the whole database, and for the sighting images in it.

    Both cover every device, not only the caller's, because the disk is shared.
    ``image_bytes`` counts full images and their thumbnails. PostgreSQL reports
    the database with ``pg_database_size``. SQLite has no such function, so the
    unit tests read the page count instead.
    """
    if db.bind.dialect.name == "postgresql":
        database_bytes = (
            await db.execute(select(func.pg_database_size(func.current_database())))
        ).scalar_one()
        size = func.octet_length
    else:
        database_bytes = (
            await db.execute(
                text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
            )
        ).scalar_one()
        size = func.length
    image_bytes = (
        await db.execute(
            select(
                func.coalesce(func.sum(size(Sighting.image_data)), 0)
                + func.coalesce(func.sum(size(Sighting.thumbnail_data)), 0)
            )
        )
    ).scalar_one()
    return {"database_bytes": int(database_bytes), "image_bytes": int(image_bytes)}
