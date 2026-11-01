import json
from datetime import datetime

from litestar import Controller, Request, get
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException
from litestar.params import FromQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..animals.controller import animal_stats
from ..animals.schemas import AnimalStatsResponse
from ..auth.guards import USER_JWT, user_guard
from ..config import settings
from ..species.ebird import ebird_code
from . import operations
from .schemas import (
    DashboardResponse,
    HourStatsResponse,
    SpeciesCountResponse,
    StorageResponse,
)


# A cap well past any real history. Without one, a huge value overflows timedelta.
MAX_DAYS = 36500


def _zone_or_400(tz: str) -> str:
    try:
        return operations.parse_zone(tz)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="tz must be an IANA time zone name, such as America/Los_Angeles",
        )


def _species_count_response(row: dict) -> SpeciesCountResponse:
    s = row["species"]
    return SpeciesCountResponse(
        id=s.id,
        common_name=s.common_name,
        genus=s.genus,
        species_name=s.species_name,
        order_name=s.order_name,
        wiki_url=s.wiki_url,
        palette=json.loads(s.palette) if s.palette else [],
        silhouette=s.silhouette,
        note=s.note,
        description=s.description,
        family=s.family,
        ebird_code=ebird_code(s.common_name, s.genus, s.species_name),
        count=row["count"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        peak_hours=row["peak_hours"],
    )


class StatsController(Controller):
    path = "/stats"
    guards = [user_guard]
    security = USER_JWT

    @get("/dashboard")
    async def dashboard(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        device_id: FromQuery[int | None] = None,
    ) -> DashboardResponse:
        """Headline numbers. With `device_id`, they cover that one feeder."""
        data = await operations.dashboard(db, request.state.user_id, device_id=device_id)
        return DashboardResponse(**data)

    @get("/species-counts")
    async def species_counts(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        tz: FromQuery[str | None] = None,
        from_date: FromQuery[str | None] = None,
        to_date: FromQuery[str | None] = None,
        device_id: FromQuery[int | None] = None,
    ) -> list[SpeciesCountResponse]:
        """Per-species totals, most frequent first.

        `from_date` and `to_date` are inclusive ISO-8601 bounds, as on
        `GET /sightings`. With them, counts cover only that range. Home sends
        the bounds of the viewer's local yesterday. With `device_id`, counts
        cover that one feeder.
        """
        zone = _zone_or_400(tz) if tz is not None else None
        try:
            from_dt = datetime.fromisoformat(from_date) if from_date else None
            to_dt = datetime.fromisoformat(to_date) if to_date else None
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="from_date/to_date must be ISO-8601 (e.g. 2026-07-19 or 2026-07-19T10:00:00Z)",
            )
        rows = await operations.species_counts(
            db,
            request.state.user_id,
            tz=zone,
            from_date=from_dt,
            to_date=to_dt,
            device_id=device_id,
        )
        return [_species_count_response(r) for r in rows]

    @get("/hours")
    async def hours(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        species_id: FromQuery[int | None] = None,
        days: FromQuery[int] = 30,
        tz: FromQuery[str] = "UTC",
        device_id: FromQuery[int | None] = None,
    ) -> HourStatsResponse:
        """Visits per local hour in `tz`. `days=0` covers all time.

        With `device_id`, visits on that one feeder only.
        """
        if not 0 <= days <= MAX_DAYS:
            raise HTTPException(
                status_code=400, detail=f"days must be 0 (all time) to {MAX_DAYS}"
            )
        data = await operations.hours(
            db,
            request.state.user_id,
            tz=_zone_or_400(tz),
            days=days or None,
            species_id=species_id,
            device_id=device_id,
        )
        return HourStatsResponse(**data)

    @get("/animals")
    async def animals(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        device_id: FromQuery[int],
        from_date: FromQuery[str | None] = None,
        to_date: FromQuery[str | None] = None,
        tz: FromQuery[str] = "UTC",
    ) -> AnimalStatsResponse:
        """Animal visits per local day and group on one feeder, with its measures.

        `from_date` and `to_date` are inclusive local dates in `tz`, 60 days to
        today by default and 366 at most. Each day also has the bird count. Each
        measure in range carries its effect: animal visits per camera-up hour in
        the 14 days before it against the days after, up to 14, as a rate ratio
        with a 95% interval. Offline hours are left out.
        """
        return await animal_stats(
            request, db, device_id=device_id, from_date=from_date, to_date=to_date, tz=tz
        )

    @get("/heatmap")
    async def heatmap(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        device_id: FromQuery[int | None] = None,
    ) -> list[list[int]]:
        """Bird visits per weekday and UTC hour, last 7 days. `device_id` scopes it."""
        return await operations.heatmap(db, request.state.user_id, device_id=device_id)

    @get("/storage")
    async def storage(self, db: NamedDependency[AsyncSession]) -> StorageResponse:
        """Database size and image storage size, for Settings.

        Both numbers cover the whole server, not only the caller's devices.
        `retention_unknown_days` is 0 when the retention rule is off.
        """
        data = await operations.storage(db)
        return StorageResponse(
            **data, retention_unknown_days=settings.RETENTION_UNKNOWN_DAYS
        )
