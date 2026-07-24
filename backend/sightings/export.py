"""Sighting history export (FLEDGE Phase 6).

Serialises a user's accessible sightings to CSV or JSON, joined against species
and device names so the file is readable on its own rather than a wall of
foreign keys.

Image bytes are deliberately **not** included — a export of a few thousand
sightings would be hundreds of megabytes, and the rows carry a `has_image` flag
plus the API path to fetch each one individually.
"""
import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, Sighting, Species
from .operations import _accessible_device_ids

# Column order is fixed and part of the contract — a spreadsheet or script
# consuming this shouldn't break because a field moved.
COLUMNS = [
    "sighting_id",
    "datetime",
    "common_name",
    "scientific_name",
    "device_name",
    "confidence_score",
    "classification_tier_used",
    "delayed",
    "weather_conditions",
    "has_image",
    "image_url",
]

MAX_ROWS = 50_000


async def collect_rows(
    db: AsyncSession,
    user_id: int,
    *,
    device_id: int | None = None,
    species_id: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = MAX_ROWS,
) -> list[dict]:
    """Flat, self-describing rows scoped to what this user may see."""
    accessible = await _accessible_device_ids(db, user_id)
    if not accessible:
        return []

    query = (
        select(Sighting, Species, Device)
        .join(Species, Species.id == Sighting.species_id)
        .join(Device, Device.id == Sighting.device_id)
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

    query = query.order_by(Sighting.datetime.desc()).limit(min(limit, MAX_ROWS))

    rows = []
    for sighting, species, device in (await db.execute(query)).all():
        scientific = f"{species.genus} {species.species_name}".strip()
        has_image = sighting.image_data is not None
        rows.append(
            {
                "sighting_id": sighting.id,
                "datetime": sighting.datetime.isoformat(),
                "common_name": species.common_name,
                "scientific_name": scientific,
                "device_name": device.name,
                "confidence_score": round(sighting.confidence_score, 4),
                "classification_tier_used": sighting.classification_tier_used,
                "delayed": sighting.delayed,
                "weather_conditions": sighting.weather_conditions or "",
                "has_image": has_image,
                "image_url": f"/sightings/{sighting.id}/image" if has_image else "",
            }
        )
    return rows


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    # newline="" semantics: csv writes \r\n itself; StringIO would otherwise
    # translate and produce \r\r\n on Windows.
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def filename(fmt: str, *, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d")
    return f"peck_deck_sightings_{stamp}.{fmt}"
