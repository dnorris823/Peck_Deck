import json
from datetime import datetime

from litestar import Controller, Request, get
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException
from litestar.params import FromQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from . import operations
from .schemas import (
    DashboardResponse,
    HourStatsResponse,
    SpeciesCountResponse,
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
        count=row["count"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        peak_hours=row["peak_hours"],
    )


class StatsController(Controller):
    path = "/stats"
    guards = [user_guard]

    @get("/dashboard")
    async def dashboard(self, request: Request, db: NamedDependency[AsyncSession]) -> DashboardResponse:
        data = await operations.dashboard(db, request.state.user_id)
        return DashboardResponse(**data)

    @get("/species-counts")
    async def species_counts(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        tz: FromQuery[str | None] = None,
        from_date: FromQuery[str | None] = None,
        to_date: FromQuery[str | None] = None,
    ) -> list[SpeciesCountResponse]:
        """Per-species totals, most frequent first.

        `from_date` and `to_date` are inclusive ISO-8601 bounds, as on
        `GET /sightings`. With them, counts cover only that range. Home sends
        the bounds of the viewer's local yesterday.
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
            db, request.state.user_id, tz=zone, from_date=from_dt, to_date=to_dt
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
    ) -> HourStatsResponse:
        """Visits per local hour in `tz`. `days=0` covers all time."""
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
        )
        return HourStatsResponse(**data)

    @get("/heatmap")
    async def heatmap(self, request: Request, db: NamedDependency[AsyncSession]) -> list[list[int]]:
        return await operations.heatmap(db, request.state.user_id)

