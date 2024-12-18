
from typing import Optional
from datetime import datetime

from pydantic import BaseModel

class SightingsCreatorStruct(BaseModel):
    species: int
    device: int
    datetime: datetime
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsUpdaterStruct(BaseModel):
    sightings_id: int
    species: Optional[int] = None
    device: Optional[int] = None
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsDeleterStruct(BaseModel):
    sightings_id: int

class SightingsCreatorRequestSchema(BaseModel):

    records_list: list[SightingsCreatorStruct]

class SightingsUpdaterRequestSchema(BaseModel):

    records_list: list[SightingsUpdaterStruct]

class SightingsDeleterRequestSchema(BaseModel):

    records_list: list[SightingsDeleterStruct]

class SightingsResponseStruct(BaseModel):
    species: int
    device: int
    datetime: datetime
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsResponseSchema(BaseModel):
    code: int
    message: str
    body: list[SightingsResponseStruct]