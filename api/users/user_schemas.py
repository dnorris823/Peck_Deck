
from pydantic import BaseModel

class UsersCreatorStruct(BaseModel):
    email: str
    password: str

class UsersUpdaterStruct(BaseModel):
    users_id: int
    email: str
    password: str

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