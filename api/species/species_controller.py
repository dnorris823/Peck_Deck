
from litestar.controller import Controller
from litestar.handlers import post, patch, delete
from litestar.di import Provide
from litestar.status_codes import HTTP_201_CREATED, HTTP_200_OK, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.connection import connect_to_db

from api.species.species_operations import SpeciesOperations

from api.species.species_schemas import (SpeciesCreatorRequestSchema, 
                                         SpeciesUpdaterRequestSchema, 
                                         SpeciesDeleterRequestSchema,
                                         SpeciesResponseSchema)


class SpeciesController(Controller):
    dependencies = {'db_connection': Provide(connect_to_db)}
    
    @post(path="/create", status_code=HTTP_201_CREATED)
    async def create_species(self, data: SpeciesCreatorRequestSchema, db_connection: async_sessionmaker) -> SpeciesResponseSchema:
        print(f"endpoint: /species/create")
        print(f"request_body: {data}")
        return await SpeciesOperations.create_species(data, db_connection)
    
    @patch(path="/update", status_code=HTTP_200_OK)
    async def update_species(self, data: SpeciesUpdaterRequestSchema, db_connection: async_sessionmaker) -> SpeciesResponseSchema:
        print(f"endpoint: /species/update")
        print(f"request_body: {data}")
        return await SpeciesOperations.update_species(data, db_connection)
    
    @delete(path="/delete", status_code=HTTP_204_NO_CONTENT)
    async def delete_species(self, data: SpeciesDeleterRequestSchema, db_connection: async_sessionmaker) -> None:
        print(f"endpoint: /species/delete")
        print(f"request_body: {data}")
        return await SpeciesOperations.delete_species(data, db_connection)