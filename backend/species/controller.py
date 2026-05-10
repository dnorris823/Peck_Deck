from litestar import Controller, get, post
from litestar.exceptions import NotFoundException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from .operations import create_species, get_species, list_species
from .schemas import CreateSpecies, SpeciesResponse


def _to_response(s) -> SpeciesResponse:
    return SpeciesResponse(
        id=s.id,
        common_name=s.common_name,
        genus=s.genus,
        species_name=s.species_name,
        order_name=s.order_name,
        wiki_url=s.wiki_url,
    )


class SpeciesController(Controller):
    path = "/species"
    guards = [user_guard]

    @get("/")
    async def list_all(self, db: AsyncSession) -> list[SpeciesResponse]:
        return [_to_response(s) for s in await list_species(db)]

    @get("/{species_id:int}")
    async def get_one(self, species_id: int, db: AsyncSession) -> SpeciesResponse:
        species = await get_species(db, species_id)
        if species is None:
            raise NotFoundException()
        return _to_response(species)

    @post("/", status_code=201)
    async def create(self, data: CreateSpecies, db: AsyncSession) -> SpeciesResponse:
        species = await create_species(
            db,
            common_name=data.common_name,
            genus=data.genus,
            species_name=data.species_name,
            order_name=data.order_name,
            wiki_url=data.wiki_url,
        )
        return _to_response(species)
