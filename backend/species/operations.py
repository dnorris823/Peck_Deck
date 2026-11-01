import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Sighting, Species

BIRD = "bird"
ANIMAL = "animal"


def is_bird_sighting():
    """A WHERE clause that keeps sightings of birds and drops animal visits.

    Every bird count and bird stat uses it, so a squirrel never shows up as a
    species, a visit, or a busy hour.
    """
    return Sighting.species_id.in_(select(Species.id).where(Species.kind == BIRD))


async def get_species(db: AsyncSession, species_id: int) -> Species | None:
    result = await db.execute(select(Species).where(Species.id == species_id))
    return result.scalar_one_or_none()


async def list_species(db: AsyncSession) -> list[Species]:
    result = await db.execute(select(Species).order_by(Species.common_name))
    return list(result.scalars().all())


async def get_or_create_species(
    db: AsyncSession,
    *,
    common_name: str,
    genus: str,
    species_name: str,
    kind: str = BIRD,
    animal_group: str | None = None,
) -> Species:
    """The species row for this name, created on first upload.

    An animal upload turns an existing bird row into an animal row. The reverse
    never happens, because a Pi build from before animals sends no kind at all,
    and that must not undo a squirrel.
    """
    result = await db.execute(
        select(Species).where(
            Species.common_name == common_name,
            Species.genus == genus,
            Species.species_name == species_name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if kind == ANIMAL and (existing.kind != ANIMAL or existing.animal_group != animal_group):
            existing.kind = ANIMAL
            existing.animal_group = animal_group
            await db.flush()
        return existing

    new_species = Species(
        common_name=common_name,
        genus=genus,
        species_name=species_name,
        kind=kind,
        animal_group=animal_group if kind == ANIMAL else None,
    )
    db.add(new_species)
    await db.flush()
    return new_species


async def create_species(
    db: AsyncSession,
    *,
    common_name: str,
    genus: str,
    species_name: str,
    order_name: str | None,
    wiki_url: str | None,
    palette: list[str] | None = None,
    silhouette: str | None = None,
    note: str | None = None,
) -> Species:
    species = Species(
        common_name=common_name,
        genus=genus,
        species_name=species_name,
        order_name=order_name,
        wiki_url=wiki_url,
        palette=json.dumps(palette) if palette else None,
        silhouette=silhouette,
        note=note,
    )
    db.add(species)
    await db.flush()
    return species
