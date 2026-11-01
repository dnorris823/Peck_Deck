"""Decide whether a bird sighting is a new species for one user.

A sighting is new in one of three ways. Only the strongest that applies counts.

1. ``first_ever``: no feeder the user can see has recorded this species.
2. ``first_at_feeder``: this feeder has not recorded it, but another has.
3. ``first_this_year``: no feeder the user can see has recorded it since
   1 January, UTC.

The new species alert skips the bird throttle and never starts it. Each kind has
its own switch in the user's preferences.

Rules that keep the push honest:

- Only bird sightings count, through ``is_bird_sighting()``. "Unknown" is never
  new, because it names no species.
- A sighting waiting for the Tier 2 re-check decides after the re-check, since
  Tier 2 may change its species. While the re-check is on, a pending row does
  not count as a record either. Otherwise a Tier 1 fallback and a later Tier 2
  answer of the same species would each hide the other, and no push would go.
- ``first_ever`` needs ``FIRST_EVER_MIN_CONFIDENCE``. A first ever push is rare
  and loud, and a wrong Tier 2 answer just over its 0.60 bar would make a false
  one. Below the floor the sighting gets the normal alert.
"""
from datetime import datetime, timezone

from sqlalchemy import or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Device, DeviceUser, Sighting, Species, UserPreferences
from ..species.operations import BIRD, is_bird_sighting

FIRST_EVER = "first_ever"
FIRST_AT_FEEDER = "first_at_feeder"
FIRST_THIS_YEAR = "first_this_year"

# At 0.70 Tier 2 accepts 2.1% of the 3,000 test photos wrongly, against 5.3% at
# 0.50 (machine_learning/MODELS.md, Calibration). An accepted Tier 1 answer is
# 0.85 or more, so the floor bites Tier 2 and Tier 3 answers in practice.
FIRST_EVER_MIN_CONFIDENCE = 0.70

# backend/sightings/recheck.py PENDING. Not imported, because the re-check
# imports this package.
_PENDING = "pending"
_UNKNOWN = "unknown"


def recheck_on() -> bool:
    return settings.TIER2_RECHECK_INTERVAL_SECONDS > 0


def waits_for_recheck(sighting: Sighting) -> bool:
    """Whether "new" waits until the Tier 2 re-check has run.

    With the re-check off, a pending row stays pending forever, so it decides now.
    """
    return sighting.tier2_recheck == _PENDING and recheck_on()


def _names_a_bird(sighting: Sighting, species: Species) -> bool:
    if species.kind != BIRD:
        return False
    if sighting.classification_tier_used == "none":
        return False
    return species.common_name.strip().lower() != _UNKNOWN


async def new_kind(
    db: AsyncSession, sighting: Sighting, species: Species, user_id: int
) -> str | None:
    """The strongest way this sighting is new for ``user_id``, or None."""
    if not _names_a_bird(sighting, species):
        return None

    feeders = union(
        select(Device.id).where(Device.owner_id == user_id),
        select(DeviceUser.device_id).where(DeviceUser.user_id == user_id),
    )
    records = select(Sighting.id).where(
        Sighting.species_id == sighting.species_id,
        Sighting.id != sighting.id,
        Sighting.device_id.in_(feeders),
        is_bird_sighting(),
    )
    if recheck_on():
        records = records.where(
            or_(Sighting.tier2_recheck.is_(None), Sighting.tier2_recheck != _PENDING)
        )

    async def none_in(query) -> bool:
        return (await db.execute(query.limit(1))).first() is None

    if await none_in(records):
        return FIRST_EVER
    if await none_in(records.where(Sighting.device_id == sighting.device_id)):
        return FIRST_AT_FEEDER
    when = sighting.datetime
    # SQLite hands back naive datetimes. They are UTC, as stored.
    year = (when.astimezone(timezone.utc) if when.tzinfo else when).year
    new_year = datetime(year, 1, 1, tzinfo=timezone.utc)
    if await none_in(records.where(Sighting.datetime >= new_year)):
        return FIRST_THIS_YEAR
    return None


def wanted(kind: str | None, prefs: UserPreferences | None, confidence: float) -> bool:
    """Whether the user gets a new species alert for ``kind``.

    The kind's switch must be on. A user with no preferences row has all three
    on. ``first_ever`` also needs the confidence floor.
    """
    if kind is None:
        return False
    if kind == FIRST_EVER and confidence < FIRST_EVER_MIN_CONFIDENCE:
        return False
    if prefs is None:
        return True
    return bool(getattr(prefs, f"notify_{kind}"))


def headline(kind: str, species_name: str, feeder_name: str) -> str:
    """The alert title, which says which kind of new it is."""
    if kind == FIRST_EVER:
        return f"New for Peck Deck: {species_name} at {feeder_name}"
    if kind == FIRST_AT_FEEDER:
        return f"New at {feeder_name}: {species_name}"
    return f"First this year: {species_name} at {feeder_name}"
