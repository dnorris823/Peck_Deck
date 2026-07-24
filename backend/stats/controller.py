import json

from litestar import Controller, Request, get
from litestar.di import NamedDependency
from litestar.params import FromQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from . import operations
from .schemas import (
    DashboardResponse,
    DeviceCountResponse,
    InsightsResponse,
    NewSpeciesResponse,
    SpeciesCountResponse,
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
        self, request: Request, db: NamedDependency[AsyncSession]
    ) -> list[SpeciesCountResponse]:
        rows = await operations.species_counts(db, request.state.user_id)
        return [_species_count_response(r) for r in rows]

    @get("/heatmap")
    async def heatmap(self, request: Request, db: NamedDependency[AsyncSession]) -> list[list[int]]:
        return await operations.heatmap(db, request.state.user_id)

    @get("/insights")
    async def insights(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        days: FromQuery[int] = 30,
        device_id: FromQuery[int | None] = None,
    ) -> InsightsResponse:
        """Analytics over a selectable window, optionally for a single device.

        `days` is clamped to 1..365 in operations so a hand-crafted query can't
        ask the server to bucket an unbounded range.
        """
        data = await operations.insights(
            db, request.state.user_id, days=days, device_id=device_id
        )
        return InsightsResponse(
            **{
                **data,
                "new_species": [NewSpeciesResponse(**n) for n in data["new_species"]],
                "per_device": [DeviceCountResponse(**d) for d in data["per_device"]],
            }
        )
