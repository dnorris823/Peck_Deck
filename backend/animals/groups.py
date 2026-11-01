"""Feeder animal groups: their push defaults, their push wording, and their rows.

``FEEDER_ANIMALS`` is the backend's copy of machine_learning/feeder_animals.csv,
because the backend image holds only backend/. A test keeps the two equal. The
migration that seeds the species rows keeps its own copy, as of its revision.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Species
from ..species.operations import ANIMAL


@dataclass(frozen=True)
class Group:
    alert_default: bool
    # {feeder} is the feeder's name.
    title: str


GROUPS: dict[str, Group] = {
    "squirrel": Group(True, "Squirrel at {feeder}"),
    "raccoon": Group(True, "Raccoon at {feeder}"),
    "bear": Group(True, "Bear at {feeder}. Bring the feeder in tonight."),
    "cat": Group(True, "Cat near {feeder}. Birds at risk."),
    "chipmunk": Group(False, "Chipmunk at {feeder}"),
    "rat": Group(False, "Rat at {feeder}"),
    "rabbit": Group(False, "Rabbit at {feeder}"),
    "opossum": Group(False, "Opossum at {feeder}"),
    "deer": Group(False, "Deer at {feeder}"),
}

# (common_name, scientific_name, group), in the CSV's order.
FEEDER_ANIMALS: list[tuple[str, str, str]] = [
    ("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel"),
    ("Fox Squirrel", "Sciurus niger", "squirrel"),
    ("Western Gray Squirrel", "Sciurus griseus", "squirrel"),
    ("Abert's Squirrel", "Sciurus aberti", "squirrel"),
    ("American Red Squirrel", "Tamiasciurus hudsonicus", "squirrel"),
    ("Douglas's Squirrel", "Tamiasciurus douglasii", "squirrel"),
    ("Southern Flying Squirrel", "Glaucomys volans", "squirrel"),
    ("Eastern Chipmunk", "Tamias striatus", "chipmunk"),
    ("Least Chipmunk", "Neotamias minimus", "chipmunk"),
    ("Yellow-pine Chipmunk", "Neotamias amoenus", "chipmunk"),
    ("Townsend's Chipmunk", "Neotamias townsendii", "chipmunk"),
    ("Raccoon", "Procyon lotor", "raccoon"),
    ("Virginia Opossum", "Didelphis virginiana", "opossum"),
    ("White-tailed Deer", "Odocoileus virginianus", "deer"),
    ("Mule Deer", "Odocoileus hemionus", "deer"),
    ("American Black Bear", "Ursus americanus", "bear"),
    ("Brown Bear", "Ursus arctos", "bear"),
    ("Domestic Cat", "Felis catus", "cat"),
    ("Brown Rat", "Rattus norvegicus", "rat"),
    ("Black Rat", "Rattus rattus", "rat"),
    ("Eastern Cottontail", "Sylvilagus floridanus", "rabbit"),
    ("Desert Cottontail", "Sylvilagus audubonii", "rabbit"),
    ("Mountain Cottontail", "Sylvilagus nuttallii", "rabbit"),
]


def alert_on(alerts: dict | None, group: str | None) -> bool:
    """Whether a user with this ``animal_alerts`` map wants a push for ``group``."""
    if group is None:
        return False
    if alerts and group in alerts:
        return bool(alerts[group])
    known = GROUPS.get(group)
    return known.alert_default if known else False


def resolved_alerts(alerts: dict | None) -> dict[str, bool]:
    """Every known group with the user's switch, or the default where unset."""
    return {group: alert_on(alerts, group) for group in GROUPS}


def alert_title(group: str, feeder: str) -> str:
    known = GROUPS.get(group)
    template = known.title if known else f"{group.capitalize()} at {{feeder}}"
    return template.format(feeder=feeder)


async def ensure_feeder_animals(db: AsyncSession) -> int:
    """Create the animal species rows that do not exist yet. Returns how many.

    Production gets them from the migration. The dev seed and the tests call
    this, because they build the schema without migrations.
    """
    created = 0
    for common, scientific, group in FEEDER_ANIMALS:
        genus, name = scientific.split(" ", 1)
        found = (
            await db.execute(
                select(Species).where(
                    Species.common_name == common,
                    Species.genus == genus,
                    Species.species_name == name,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            db.add(Species(common_name=common, genus=genus, species_name=name,
                           kind=ANIMAL, animal_group=group))
            created += 1
    await db.flush()
    return created
