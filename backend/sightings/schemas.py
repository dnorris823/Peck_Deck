from dataclasses import dataclass
from datetime import datetime


@dataclass
class SightingResponse:
    id: int
    species_id: int
    device_id: int
    datetime: str
    classification_tier_used: str
    confidence_score: float
    weather_conditions: str | None
    delayed: bool
    has_image: bool


def sighting_response(s) -> SightingResponse:
    """Serialize a ``Sighting`` row for the wire.

    Shared by ``GET /sightings`` and the ``GET /events`` stream on purpose: a
    streamed sighting has to be indistinguishable from a fetched one, because
    the web app maps both through the same function and prepends the streamed
    one straight into the list it got from the fetch.
    """
    return SightingResponse(
        id=s.id,
        species_id=s.species_id,
        device_id=s.device_id,
        datetime=s.datetime.isoformat(),
        classification_tier_used=s.classification_tier_used,
        confidence_score=s.confidence_score,
        weather_conditions=s.weather_conditions,
        delayed=s.delayed,
        has_image=s.image_data is not None,
    )


@dataclass
class SightingListParams:
    device_id: int | None = None
    species_id: int | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = 50
    offset: int = 0
