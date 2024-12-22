
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Sightings
from api.sightings.sighting_schemas import (SightingsCreatorRequestSchema,
                                         SightingsUpdaterRequestSchema,
                                         SightingsDeleterRequestSchema,
                                         SightingsResponseStruct,
                                         SightingsResponseSchema)

class SightingsOperations:
    
    async def create_sightings(req_data: SightingsCreatorRequestSchema, db_connection: async_sessionmaker) -> SightingsResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            new_sighting_list = []

            for record in req_data.get('records_list'):

                new_sighting = Sightings(**record)
                new_sighting_list.append(new_sighting)

            session.add_all(new_sighting_list)
            await session.commit()
            
            new_sightings_body = [SightingsResponseStruct(sighting_id=new_sighting.id,
                                                          species_id=new_sighting.species_id,
                                                          device_id=new_sighting.device_id,
                                                          datetime=new_sighting.datetime,
                                                          photo_storage_location=new_sighting.photo_storage_location,
                                                          weather_conditions=new_sighting.weather_conditions,
                                                          feed_type=new_sighting.feed_type) for new_sighting in new_sighting_list]

            return SightingsResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=new_sightings_body)
            
    async def update_sightings(req_data: SightingsUpdaterRequestSchema, db_connection: async_sessionmaker) -> SightingsResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:
            
            updated_sighting_list = []
            
            for record in req_data.get('records_list'):
                updated_sighting = await session.execute(select(Sightings).where(Sightings.id == record.get("sighting_id")))
                updated_sighting = updated_sighting.scalar_one()

                # go through all optional items in request and update sightings if present
                for k, v in record.items():
                    if k != 'sightings_id' and v is not None:
                        setattr(updated_sighting, k, v)

                updated_sighting_list.append(updated_sighting)

            await session.commit()
            
            updated_sightings_body = [SightingsResponseStruct(sighting_id=updated_sighting.id,
                                                          species_id=updated_sighting.species_id,
                                                          device_id=updated_sighting.device_id,
                                                          datetime=updated_sighting.datetime,
                                                          photo_storage_location=updated_sighting.photo_storage_location,
                                                          weather_conditions=updated_sighting.weather_conditions,
                                                          feed_type=updated_sighting.feed_type) for updated_sighting in updated_sighting_list]

            return SightingsResponseSchema(code=200,
                                        message='request handled successfully!',
                                        body=updated_sightings_body)
            
    async def delete_sightings(req_data: SightingsDeleterRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            for record in req_data.get('records_list'):
                # create sightings instance of row from database table sightingss with specified sightings_id
                sighting = await session.execute(select(Sightings).where(Sightings.id == record.get("sighting_id")))
                sighting = sighting.scalar_one()

                await session.delete(sighting)

            await session.commit()

            return None       