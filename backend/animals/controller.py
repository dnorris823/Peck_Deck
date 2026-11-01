"""Measures on a feeder, and the animal stats behind the Animals view."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from litestar import Controller, Request, delete, get, patch, post
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import FromPath
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import USER_JWT, user_guard
from ..database.models import Device, FeederMeasure
from ..devices.operations import as_utc, get_device
from ..sightings.operations import user_can_access_device
from . import operations as ops
from .schemas import (
    AnimalDay,
    AnimalStatsResponse,
    CreateMeasure,
    MeasureEffectResponse,
    MeasureResponse,
    MeasureWithEffect,
    RateRatioResponse,
    UpdateMeasure,
)

MAX_NAME = 120
MAX_NOTE = 1000
# The chart covers at most this many days, and 60 by default.
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 60


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else as_utc(dt).isoformat()


def _when(raw: str, field: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be ISO-8601") from None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _name(raw: str) -> str:
    name = raw.strip()
    if not name or len(name) > MAX_NAME:
        raise HTTPException(status_code=400, detail=f"name must be 1 to {MAX_NAME} characters")
    return name


def _note(raw: str | None) -> str | None:
    note = (raw or "").strip() or None
    if note is not None and len(note) > MAX_NOTE:
        raise HTTPException(status_code=400, detail=f"note must be at most {MAX_NOTE} characters")
    return note


def measure_response(m: FeederMeasure) -> MeasureResponse:
    return MeasureResponse(
        id=m.id, device_id=m.device_id, name=m.name,
        started_at=_iso(m.started_at), ended_at=_iso(m.ended_at), note=m.note,
    )


def _ratio(r: ops.RateRatio) -> RateRatioResponse:
    return RateRatioResponse(
        before=r.before, after=r.after, before_rate=r.before_rate, after_rate=r.after_rate,
        ratio=r.ratio, low=r.low, high=r.high,
    )


def effect_response(e: ops.Effect) -> MeasureEffectResponse:
    return MeasureEffectResponse(
        before_start=_iso(e.before_start),
        after_start=_iso(e.after_start),
        after_end=_iso(e.after_end),
        before_hours=round(e.before_hours, 2),
        after_hours=round(e.after_hours, 2),
        complete=e.complete,
        groups={g: _ratio(r) for g, r in e.groups.items()},
        birds=_ratio(e.birds),
    )


async def _device_for(db: AsyncSession, request: Request, device_id: int) -> Device:
    device = await get_device(db, device_id)
    if device is None or not await user_can_access_device(
        db, request.state.user_id, request.state.role, device.id, device.owner_id
    ):
        # A feeder the user cannot see reads as missing, as on GET /devices.
        raise NotFoundException()
    return device


def _assert_feeder_owner(request: Request, device: Device) -> None:
    """The feeder's owner or an owner-role user, as for refills."""
    if device.owner_id != request.state.user_id and request.state.role != "owner":
        raise HTTPException(status_code=403, detail="Forbidden")


class MeasureController(Controller):
    path = "/devices/{device_id:int}/measures"
    guards = [user_guard]
    security = USER_JWT

    @get("/")
    async def list_all(
        self, device_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> list[MeasureResponse]:
        """The feeder's measures, oldest first. Anyone who can see the feeder."""
        await _device_for(db, request, device_id)
        return [measure_response(m) for m in await ops.list_measures(db, device_id)]

    @post("/", status_code=201)
    async def create(
        self, device_id: FromPath[int], data: CreateMeasure, request: Request,
        db: NamedDependency[AsyncSession],
    ) -> MeasureResponse:
        """Log a measure, such as "Baffle on the pole". **Feeder owner or owner role.**"""
        device = await _device_for(db, request, device_id)
        _assert_feeder_owner(request, device)
        now = datetime.now(timezone.utc)
        started = _when(data.started_at, "started_at") if data.started_at else now
        if started > now + timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="started_at cannot be in the future")
        measure = await ops.create_measure(
            db, device.id, name=_name(data.name), started_at=started, note=_note(data.note)
        )
        return measure_response(measure)

    @patch("/{measure_id:int}")
    async def update(
        self, device_id: FromPath[int], measure_id: FromPath[int], data: UpdateMeasure,
        request: Request, db: NamedDependency[AsyncSession],
    ) -> MeasureResponse:
        """Rename, move, end or reopen a measure. **Feeder owner or owner role.**

        `ended_at` ends it. An empty `ended_at` clears the end.
        """
        device = await _device_for(db, request, device_id)
        _assert_feeder_owner(request, device)
        measure = await ops.get_measure(db, device.id, measure_id)
        if measure is None:
            raise NotFoundException()
        if data.name is not None:
            measure.name = _name(data.name)
        if data.note is not None:
            measure.note = _note(data.note)
        if data.started_at is not None:
            measure.started_at = _when(data.started_at, "started_at")
        if data.ended_at is not None:
            measure.ended_at = _when(data.ended_at, "ended_at") if data.ended_at else None
        if measure.ended_at is not None and as_utc(measure.ended_at) < as_utc(measure.started_at):
            raise HTTPException(status_code=400, detail="ended_at must not be before started_at")
        await db.flush()
        return measure_response(measure)

    @delete("/{measure_id:int}", status_code=204)
    async def remove(
        self, device_id: FromPath[int], measure_id: FromPath[int], request: Request,
        db: NamedDependency[AsyncSession],
    ) -> None:
        """Delete a measure. **Feeder owner or owner role.**"""
        device = await _device_for(db, request, device_id)
        _assert_feeder_owner(request, device)
        measure = await ops.get_measure(db, device.id, measure_id)
        if measure is None:
            raise NotFoundException()
        await ops.delete_measure(db, measure)


def _zone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="tz must be an IANA time zone name, such as America/Los_Angeles",
        ) from None
    return tz


def _day(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be a date, such as 2026-11-01") from None


async def animal_stats(
    request: Request,
    db: AsyncSession,
    *,
    device_id: int,
    from_date: str | None,
    to_date: str | None,
    tz: str,
) -> AnimalStatsResponse:
    """The body of ``GET /stats/animals``. See ``StatsController.animals``."""
    zone = _zone(tz)
    device = await _device_for(db, request, device_id)
    now = datetime.now(timezone.utc)
    last = _day(to_date, "to_date") if to_date else now.astimezone(ZoneInfo(zone)).date()
    first = (
        _day(from_date, "from_date") if from_date
        else last - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    )
    if first > last:
        raise HTTPException(status_code=400, detail="from_date must not be after to_date")
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"the range is at most {MAX_RANGE_DAYS} days")

    days = await ops.daily_counts(db, device.id, first, last, zone)
    totals: dict[str, int] = {}
    for day in days:
        for group, count in day["animals"].items():
            totals[group] = totals.get(group, 0) + count

    start, end = ops.day_bounds(first, last, zone)
    measures = []
    for m in await ops.measures_in_range(db, device.id, start, end):
        effect = await ops.measure_effect(db, device, m, now)
        measures.append(MeasureWithEffect(**vars(measure_response(m)), effect=effect_response(effect)))

    return AnimalStatsResponse(
        device_id=device.id,
        tz=zone,
        from_date=first.isoformat(),
        to_date=last.isoformat(),
        days=[AnimalDay(**d) for d in days],
        groups=sorted(totals, key=lambda g: (-totals[g], g)),
        measures=measures,
    )
