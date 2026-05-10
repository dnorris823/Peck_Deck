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


@dataclass
class SightingListParams:
    device_id: int | None = None
    species_id: int | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = 50
    offset: int = 0
