


from typing import Optional
from pydantic import BaseModel


class DevicesCreatorStruct(BaseModel):
    name: str
    city: str
    state: str
    owner: int

class DevicesUpdaterStruct(BaseModel):
    device_id: int
    name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    owner: Optional[int] = None

class DevicesDeleterStruct(BaseModel):
    device_id: int
    
class DevicesAddUsersStruct(BaseModel):
    device_id: int
    user_id: int
    
class DevicesRemoveUsersStruct(BaseModel):
    device_user_id: int
    
class DevicesCreatorRequestSchema(BaseModel):

    records_list: list[DevicesCreatorStruct]

class DevicesUpdaterRequestSchema(BaseModel):

    records_list: list[DevicesUpdaterStruct]

class DevicesDeleterRequestSchema(BaseModel):

    records_list: list[DevicesDeleterStruct]
    
class DevicesAddUsersRequestSchema(BaseModel):

    records_list: list[DevicesAddUsersStruct]
    
class DevicesRemoveUsersRequestSchema(BaseModel):

    records_list: list[DevicesRemoveUsersStruct]

class DevicesResponseStruct(BaseModel):
    device_id: int
    name: str
    city: str
    state: str
    owner: int
    device_user_id: Optional[int] = None
    
class DevicesAddUsersResponseStruct(BaseModel):
    device_user_id: int
    device_id: int
    user_id: int

class DevicesResponseSchema(BaseModel):
    code: int
    message: str
    body: list[DevicesResponseStruct]
    
class DevicesAddUsersResponseSchema(BaseModel):
    code: int
    message: str
    body: list[DevicesAddUsersResponseStruct]