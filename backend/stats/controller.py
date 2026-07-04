import json

from litestar import Controller, Request, get
from litestar.di import NamedDependency
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from . import operations
from .schemas import DashboardResponse, SpeciesCountResponse


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
