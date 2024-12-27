
from typing import Optional

from pydantic import BaseModel

class ViewUsersRequestSchema(BaseModel):
    user_id: Optional[str] = None
    
class ViewDevicesRequestSchema(BaseModel):
    device_id: Optional[str] = None 
    user_id: Optional[str] = None  
    
class ViewSpeciesRequestSchema(BaseModel):
    species_id: Optional[str] = None
    
class ViewSightingsRequestSchema(BaseModel):
    sighting_id: Optional[str] = None
    device_id: Optional[str] = None
    
class ViewUsersResponseStruct(BaseModel):
    user_id: int
    email: str
    owned_devices: list[int]
    
class ViewDevicesResponseStruct(BaseModel):
    device_id: int
    name: str
    city: str
    state: str
    owner: int
    device_users: list[ViewUsersResponseStruct]
    sighting_ids: list[int]
    
class ViewSpeciesResponseStruct(BaseModel):
    species_id: int
    common_name: str
    genus: str
    species: str
    order: str
    wiki_url: str
    sighting_ids: list[int]
    
class ViewSightingsResponseStruct(BaseModel):
    sighting_id: int
    device_id: int
    species_id: int
    datetime: str
    photo_storage_location: str
    weather_conditions: str
    feed_type: str
    
class ViewUsersResponseSchema(BaseModel):
    code: int
    message: str
    body: list[ViewUsersResponseStruct]
    
class ViewDevicesResponseSchema(BaseModel):
    code: int
    message: str
    body: list[ViewDevicesResponseStruct]
    
class ViewSpeciesResponseSchema(BaseModel):
    code: int
    message: str
    body: list[ViewSpeciesResponseStruct]
    
class ViewSightingsResponseSchema(BaseModel):
    code: int
    message: str
    body: list[ViewSightingsResponseStruct]
    
  
    
    
    
    
    
    