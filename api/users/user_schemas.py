from typing import Optional
from pydantic import BaseModel

class UsersCreatorStruct(BaseModel):
    email: str
    password: str

class UsersUpdaterStruct(BaseModel):
    users_id: int
    email: Optional[str] = None
    password: Optional[str] = None

class UsersDeleterStruct(BaseModel):
    users_id: int

class UsersCreatorRequestSchema(BaseModel):

    records_list: list[UsersCreatorStruct]

class UsersUpdaterRequestSchema(BaseModel):

    records_list: list[UsersUpdaterStruct]

class UsersDeleterRequestSchema(BaseModel):

    records_list: list[UsersDeleterStruct]
    
class UsersResponseStruct(BaseModel):
    users_id: int
    email: str

class UsersResponseSchema(BaseModel):
    code: int
    message: str
    body: list[UsersResponseStruct]