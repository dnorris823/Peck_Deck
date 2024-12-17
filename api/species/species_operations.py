
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Species
from api.species.species_schemas import (SpeciesCreatorRequestSchema,
                                         SpeciesUpdaterRequestSchema,
                                         SpeciesDeleterRequestSchema,
                                         SpeciesResponseStruct,
                                         SpeciesResponseSchema)

async def create_species(req_data: SpeciesCreatorRequestSchema, 
                         db_connection: async_sessionmaker) -> SpeciesResponseSchema:

    req_data = req_data.model_dump()

    async with db_connection.async_session() as session:

        new_species_list = []

        for record in req_data.get('records_list'):

            new_species = Species(**record)
            new_species_list.append(new_species)

        session.add(new_species)
        await session.commit()

        return SpeciesResponseSchema(code=201,
                                     message='request handled successfully!',
                                     body=[SpeciesResponseStruct(**new_species.as_dict()) for new_species in new_species_list])
        
async def update_species(req_data: SpeciesUpdaterRequestSchema, 
                         db_connection: async_sessionmaker) -> SpeciesResponseSchema:

    req_data = req_data.model_dump()

    async with db_connection.async_session() as session:
        
        updated_species_list = []
        
        for record in req_data.get('records_list'):
            updated_species = await session.execute(select(Species).where(Species.id == record.get("species_id")))
            updated_species = updated_species.scalar_one()

            # go through all optional items in request and update species if present
            for k, v in record.items():
                if k != 'species_id':
                    setattr(updated_species, k, v)

            updated_species_list.append(updated_species)

        await session.commit()

        return SpeciesResponseSchema(code=200,
                                     message='request handled successfully!',
                                     body=[SpeciesResponseStruct(**updated_species.as_dict()) for updated_species in updated_species_list])
        
async def delete_species(req_data: SpeciesDeleterRequestSchema, db_connection: async_sessionmaker):

    req_data = req_data.model_dump()

    async with db_connection.async_session() as session:

        for record in req_data.get('records_list'):
            # create species instance of row from database table speciess with specified species_id
            species = await session.execute(select(Species).where(Species.id == record.get("species_id")))
            species = species.scalar_one()

            await session.delete(species)

        await session.commit()

        return None       