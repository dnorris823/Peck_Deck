from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..database.models import Device, DeviceUser, Sighting
from ..species.operations import get_or_create_species

# The list and export queries use both. The database answers "has an image?"
# itself, and the bytes stay there. A page of 100 rows would
# otherwise read about 30 MB of JPEGs to fill a bool. raiseload makes a later
# touch of `image_data` raise, instead of quietly loading it one row at a time.
HAS_IMAGE = Sighting.image_data.is_not(None).label("has_image")
SKIP_IMAGE = defer(Sighting.image_data, raiseload=True)


async def _accessible_device_ids(db: AsyncSession, user_id: int) -> list[int]:
    owned = select(Device.id).where(Device.owner_id == user_id)
    member = select(DeviceUser.device_id).where(DeviceUser.user_id == user_id)
    result = await db.execute(
        select(Device.id).where(or_(Device.id.in_(owned), Device.id.in_(member)))
    )
    return [row[0] for row in result.all()]


async def list_sightings(
    db: AsyncSession,
    user_id: int,
    *,
    device_id: int | None,
    species_id: int | None,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
    offset: int,
) -> list[tuple[Sighting, bool]]:
    """Sightings this user may see, each paired with its ``has_image`` flag."""
    accessible = await _accessible_device_ids(db, user_id)
    query = (
        select(Sighting, HAS_IMAGE)
        .options(SKIP_IMAGE)
        .where(Sighting.device_id.in_(accessible))
    )

    if device_id is not None:
        query = query.where(Sighting.device_id == device_id)
    if species_id is not None:
        query = query.where(Sighting.species_id == species_id)
    if from_date is not None:
        query = query.where(Sighting.datetime >= from_date)
    if to_date is not None:
        query = query.where(Sighting.datetime <= to_date)

    query = query.order_by(Sighting.datetime.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [(sighting, bool(has_image)) for sighting, has_image in result.all()]


async def get_sighting(db: AsyncSession, sighting_id: int) -> Sighting | None:
    result = await db.execute(select(Sighting).where(Sighting.id == sighting_id))
    return result.scalar_one_or_none()


async def create_sighting(
    db: AsyncSession,
    *,
    device_id: int,
    timestamp: str,
    common_name: str,
    scientific_name: str,
    confidence_score: float,
    classification_tier_used: str,
    image_data: bytes | None,
    delayed: bool,
) -> Sighting:
    parts = scientific_name.strip().split()
    genus = parts[0] if parts else common_name
    species_name = parts[1] if len(parts) > 1 else "sp."

    species = await get_or_create_species(
        db, common_name=common_name, genus=genus, species_name=species_name
    )

    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    sighting = Sighting(
        species_id=species.id,
        device_id=device_id,
        datetime=dt,
        image_data=image_data,
        classification_tier_used=classification_tier_used,
        confidence_score=confidence_score,
        delayed=delayed,
    )
    db.add(sighting)
    await db.flush()
    return sighting
