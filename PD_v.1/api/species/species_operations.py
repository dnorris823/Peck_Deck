
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Species
from api.species.species_schemas import (SpeciesCreatorRequestSchema,
                                         SpeciesUpdaterRequestSchema,
                                         SpeciesDeleterRequestSchema,
                                         SpeciesResponseStruct,
                                         SpeciesResponseSchema)

class SpeciesOperations:
    
    async def create_species(req_data: SpeciesCreatorRequestSchema, 
                            db_connection: async_sessionmaker) -> SpeciesResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            new_species_list = []

            for record in req_data.get('records_list'):

                new_species = Species(**record)
                new_species_list.append(new_species)

            session.add_all(new_species_list)
            await session.commit()
            
            new_species_body = [SpeciesResponseStruct(species_id=new_species.id,
                                                      common_name=new_species.common_name, 
                                                      genus=new_species.genus,
                                                      species=new_species.species,
                                                      order=new_species.order,
                                                      wiki_url=new_species.wiki_url) for new_species in new_species_list]

            return SpeciesResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=new_species_body)
            
    async def update_species(req_data: SpeciesUpdaterRequestSchema, 
                            db_connection: async_sessionmaker) -> SpeciesResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:
            
            updated_species_list = []
            
            for record in req_data.get('records_list'):
                updated_species = await session.execute(select(Species).where(Species.id == record.get("species_id")))
                updated_species = updated_species.scalar_one()

                # go through all optional items in request and update species if present
                for k, v in record.items():
                    if k != 'species_id' and v is not None:
                        setattr(updated_species, k, v)

                updated_species_list.append(updated_species)

            await session.commit()
            
            updated_species_body = [SpeciesResponseStruct(species_id=updated_species.id,
                                                      common_name=updated_species.common_name, 
                                                      genus=updated_species.genus,
                                                      species=updated_species.species,
                                                      order=updated_species.order,
                                                      wiki_url=updated_species.wiki_url) for updated_species in updated_species_list]

            return SpeciesResponseSchema(code=200,
                                        message='request handled successfully!',
                                        body=updated_species_body)
            
    async def delete_species(req_data: SpeciesDeleterRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            for record in req_data.get('records_list'):
                # create species instance of row from database table speciess with specified species_id
                species = await session.execute(select(Species).where(Species.id == record.get("species_id")))
                species = species.scalar_one()

                await session.delete(species)

            await session.commit()

            return None       