from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Species


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
) -> Species:
    result = await db.execute(
        select(Species).where(
            Species.common_name == common_name,
            Species.genus == genus,
            Species.species_name == species_name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    new_species = Species(
        common_name=common_name,
        genus=genus,
        species_name=species_name,
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
) -> Species:
    species = Species(
        common_name=common_name,
        genus=genus,
        species_name=species_name,
        order_name=order_name,
        wiki_url=wiki_url,
    )
    db.add(species)
    await db.flush()
    return species
