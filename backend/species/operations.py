import json

from sqlalchemy import func, select
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


# The species the Pi files a capture under when no tier names it. It is a bird
# row, because the camera decided it was a bird, so is_bird_sighting() keeps it.
UNKNOWN = "unknown"


def is_unknown_name(common_name: str) -> bool:
    """Whether a species with this common name is "Unknown". names_a_species() in Python."""
    return common_name.strip().lower() == UNKNOWN


def names_a_species():
    """A WHERE clause that drops sightings filed under "Unknown".

    Visits still count "Unknown": it was a bird at the feeder, so the visit
    counts, the busy hours and the feed check keep it. Species counts never do,
    because it names no species. A life list, a species total or a "new
    species" check pairs this with is_bird_sighting().
    """
    unknown = select(Species.id).where(func.lower(func.trim(Species.common_name)) == UNKNOWN)
    return Sighting.species_id.not_in(unknown)


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
