
from litestar.controller import Controller
from litestar.handlers import post, patch, delete
from litestar.di import Provide
from litestar.status_codes import HTTP_201_CREATED, HTTP_200_OK, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db

from api.devices.device_operations import DeviceOperations

from api.devices.device_schemas import (DevicesCreatorRequestSchema, 
                                         DevicesUpdaterRequestSchema, 
                                         DevicesDeleterRequestSchema,
                                         DevicesAddUsersRequestSchema,
                                         DevicesRemoveUsersRequestSchema,
                                         DevicesAddUsersResponseSchema,
                                         DevicesResponseSchema)


class DeviceController(Controller):
    dependencies = {'db_connection': Provide(connect_to_db)}
    
    @post(path="/create", status_code=HTTP_201_CREATED)
    async def create_devices(self, data: DevicesCreatorRequestSchema, db_connection: async_sessionmaker) -> DevicesResponseSchema:
        print(f"endpoint: /devices/create")
        print(f"request_body: {data}")
        return await DeviceOperations.create_devices(data, db_connection)
    
    @patch(path="/update", status_code=HTTP_200_OK)
    async def update_devices(self, data: DevicesUpdaterRequestSchema, db_connection: async_sessionmaker) -> DevicesResponseSchema:
        print(f"endpoint: /devices/update")
        print(f"request_body: {data}")
        return await DeviceOperations.update_devices(data, db_connection)
    
    @delete(path="/delete", status_code=HTTP_204_NO_CONTENT)
    async def delete_devices(self, data: DevicesDeleterRequestSchema, db_connection: async_sessionmaker) -> None:
        print(f"endpoint: /devices/delete")
        print(f"request_body: {data}")
        return await DeviceOperations.delete_devices(data, db_connection)
    
    @post(path="/add_users", status_code=HTTP_201_CREATED)
    async def add_users_to_device(self, data: DevicesAddUsersRequestSchema, db_connection: async_sessionmaker) -> DevicesAddUsersResponseSchema:
        print(f"endpoint: /devices/add_users")
        print(f"request_body: {data}")
        return await DeviceOperations.add_users_to_device(data, db_connection)
    
    @delete(path="/remove_users", status_code=HTTP_201_CREATED)
    async def remove_users_from_device(self, data: DevicesRemoveUsersRequestSchema, db_connection: async_sessionmaker) -> None:
        print(f"endpoint: /devices/remove_users")
        print(f"request_body: {data}")
        return await DeviceOperations.remove_users_from_device(data, db_connection)