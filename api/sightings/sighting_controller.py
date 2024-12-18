
from litestar.controller import Controller
from litestar.handlers import post, patch, delete
from litestar.di import Provide
from litestar.status_codes import HTTP_201_CREATED, HTTP_200_OK, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db

from api.sightings.sighting_operations import SightingsOperations

from api.sightings.sighting_schemas import (SightingsCreatorRequestSchema, 
                                         SightingsUpdaterRequestSchema, 
                                         SightingsDeleterRequestSchema,
                                         SightingsResponseSchema)


class SightingsController(Controller):
    dependencies = {'db_connection': Provide(connect_to_db)}
    
    @post(path="/create", status_code=HTTP_201_CREATED)
    async def create_sightings(self, data: SightingsCreatorRequestSchema, db_connection: async_sessionmaker) -> SightingsResponseSchema:
        print(f"endpoint: /sightings/create")
        print(f"request_body: {data}")
        return await SightingsOperations.create_sightings(data, db_connection)
    
    @patch(path="/update", status_code=HTTP_200_OK)
    async def update_sightings(self, data: SightingsUpdaterRequestSchema, db_connection: async_sessionmaker) -> SightingsResponseSchema:
        print(f"endpoint: /sightings/update")
        print(f"request_body: {data}")
        return await SightingsOperations.update_sightings(data, db_connection)
    
    @delete(path="/delete", status_code=HTTP_204_NO_CONTENT)
    async def delete_sightings(self, data: SightingsDeleterRequestSchema, db_connection: async_sessionmaker) -> None:
        print(f"endpoint: /sightings/delete")
        print(f"request_body: {data}")
        return await SightingsOperations.delete_sightings(data, db_connection)