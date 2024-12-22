
from typing import Optional
from datetime import datetime

from pydantic import BaseModel

class SightingsCreatorStruct(BaseModel):
    species_id: int
    device_id: int
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsUpdaterStruct(BaseModel):
    sighting_id: int
    species_id: Optional[int] = None
    device_id: Optional[int] = None
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsDeleterStruct(BaseModel):
    sighting_id: int

class SightingsCreatorRequestSchema(BaseModel):

    records_list: list[SightingsCreatorStruct]

class SightingsUpdaterRequestSchema(BaseModel):

    records_list: list[SightingsUpdaterStruct]

class SightingsDeleterRequestSchema(BaseModel):

    records_list: list[SightingsDeleterStruct]

class SightingsResponseStruct(BaseModel):
    sighting_id: int
    species_id: int
    device_id: int
    datetime: datetime
    photo_storage_location: Optional[str] = None
    weather_conditions: Optional[str] = None
    feed_type: Optional[str] = None

class SightingsResponseSchema(BaseModel):
    code: int
    message: str
    body: list[SightingsResponseStruct]