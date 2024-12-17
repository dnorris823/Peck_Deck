
from litestar.controller import Controller
from litestar.handlers import post, patch, delete
from litestar.di import Provide
from litestar.status_codes import HTTP_201_CREATED, HTTP_200_OK, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db

from api.users.user_operations import (create_users,
                                            update_users,
                                            delete_users)

from api.users.user_schemas import (UsersCreatorRequestSchema, 
                                         UsersUpdaterRequestSchema, 
                                         UsersDeleterRequestSchema,
                                         UsersResponseSchema)

class UsersController(Controller):
    dependencies = {'db_connection': Provide(connect_to_db)}
    
    @post(path="/create", status_code=HTTP_201_CREATED)
    async def create_users(self, data: UsersCreatorRequestSchema, db_connection: async_sessionmaker) -> UsersResponseSchema:
        print(f"endpoint: /users/create")
        print(f"request_body: {data}")
        return await create_users(data, db_connection)
    
    @patch(path="/update", status_code=HTTP_200_OK)
    async def update_users(self, data: UsersUpdaterRequestSchema, db_connection: async_sessionmaker) -> UsersResponseSchema:
        print(f"endpoint: /users/update")
        print(f"request_body: {data}")
        return await update_users(data, db_connection)
    
    @delete(path="/delete", status_code=HTTP_204_NO_CONTENT)
    async def create_users(self, data: UsersDeleterRequestSchema, db_connection: async_sessionmaker) -> None:
        print(f"endpoint: /users/delete")
        print(f"request_body: {data}")
        return await delete_users(data, db_connection)