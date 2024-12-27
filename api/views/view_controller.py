
from litestar.controller import Controller
from litestar.handlers import get
from litestar.di import Provide
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db

from api.views.view_operations import ViewOperations
from api.views.view_schemas import (ViewUsersRequestSchema, 
                                    ViewUsersResponseSchema, 
                                    ViewDevicesRequestSchema, 
                                    ViewDevicesResponseSchema, 
                                    ViewSpeciesRequestSchema, 
                                    ViewSpeciesResponseSchema, 
                                    ViewSightingsRequestSchema, 
                                    ViewSightingsResponseSchema)

class ViewController(Controller):
    dependencies = {'db_connection': Provide(connect_to_db)}
    
    @get(path="/users", status_code=HTTP_200_OK)
    async def view_users(self, request_data: ViewUsersRequestSchema, db_connection: async_sessionmaker) -> ViewUsersResponseSchema:
        print(f"endpoint: /view/users")
        print(f"request_body: {request_data}")
        return await ViewOperations.view_users(request_data, db_connection)
    
    @get(path="/devices", status_code=HTTP_200_OK)
    async def view_devices(self, request_data: ViewDevicesRequestSchema, db_connection: async_sessionmaker) -> ViewDevicesResponseSchema:
        print(f"endpoint: /view/devices")
        print(f"request_body: {request_data}")
        return await ViewOperations.view_devices(request_data, db_connection)
    
    @get(path="/species", status_code=HTTP_200_OK)
    async def view_species(self, request_data: ViewSpeciesRequestSchema, db_connection: async_sessionmaker) -> ViewSpeciesResponseSchema:
        print(f"endpoint: /view/species")
        print(f"request_body: {request_data}")
        return await ViewOperations.view_species(request_data, db_connection)
    
    @get(path="/sightings", status_code=HTTP_200_OK)
    async def view_sightings(self, request_data: ViewSightingsRequestSchema, db_connection: async_sessionmaker) -> ViewSightingsResponseSchema:
        print(f"endpoint: /view/sightings")
        print(f"request_body: {request_data}")
        return await ViewOperations.view_sightnings(request_data, db_connection)