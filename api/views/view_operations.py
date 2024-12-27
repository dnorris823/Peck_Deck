
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select, func

from database.models import (Users, 
                             Devices,
                             DeviceUsers, 
                             Species, 
                             Sightings)

from api.views.view_schemas import (ViewUsersRequestSchema,
                                    ViewUsersResponseSchema,
                                    ViewDevicesRequestSchema,
                                    ViewDevicesResponseSchema,
                                    ViewSpeciesRequestSchema,
                                    ViewSpeciesResponseSchema,
                                    ViewSightingsRequestSchema,
                                    ViewSightingsResponseSchema,
                                    ViewUsersResponseStruct,
                                    ViewDevicesResponseStruct,
                                    ViewSpeciesResponseStruct,
                                    ViewSightingsResponseStruct)

class ViewOperations:
    
    def format_query_params(self, request_data):
        formatted_query_params = {}

        request_data = request_data.model_dump()
        
        for key, item in request_data.items():
            if key not in ['limit']:
                if item is None:
                    formatted_query_params[key] = None
                else:
                    if 'id' in key:
                        formatted_item = item.replace('[', '').replace(']', '')
                        formatted_query_params[key] = list(map(int, formatted_item.split(',')))
                    else:
                        formatted_query_params[key] = item.replace('[', '').replace(']', '').split(',')
            else:
                formatted_query_params[key] = item

        return formatted_query_params
    
    async def view_users(self, request_data: ViewUsersRequestSchema, db_connection: async_sessionmaker) -> ViewUsersResponseSchema:
        
        request_data = self.format_query_params(request_data)
        
        async with db_connection() as db_session:
            
            devices_subquery = select(func.array_agg(Devices.id).label("owned_devices"), Devices.owner).group_by(
            Devices.owner).subquery()
            
            select_statement = select(Users, 
                                      devices_subquery.c.owner_devices) \
                                .join(devices_subquery, isouter=True)
            
            if request_data.get('user_id', None):
                select_statement = select_statement.where(Users.id.in_(request_data.get('user_id', None)))
            
            view = await db_session.execute(select_statement)
            view = view.scalars().all()
            
            view_users_body = []
            
            for record in view:
                user_record = ViewUsersResponseStruct(user_id=record[0].id, 
                                                      email=record[0].email, 
                                                      owned_devices=record[1])
                view_users_body.append(user_record)
            
            return ViewUsersResponseSchema(code=200, 
                                           message='request handled successfully!', 
                                           body=view_users_body)
    
    
    async def view_devices(self, request_data: ViewDevicesRequestSchema, db_connection: async_sessionmaker) -> ViewDevicesResponseSchema:
        
        request_data = self.format_query_params(request_data)
        
        devices_user_subquery = select(func.array_agg(DeviceUsers.id).label("device_users"), Devices.device_id).group_by(
        DeviceUsers.device_id).subquery()
        
        sightings_subquery = select(func.array_agg(Sightings).label("sightings"), Sightings.device_id).group_by(
        Sightings.device_id).subquery()
        
        async with db_connection() as db_session:
            
            select_statement = select(Devices,
                                        devices_user_subquery.c.device_users,
                                        sightings_subquery.c.sightings) \
                                    .join(devices_user_subquery, isouter=True) \
                                    .join(sightings_subquery, isouter=True)
                                    
            if request_data.get('device_id', None):
                select_statement = select_statement.where(Devices.id.in_(request_data.get('device_id', None)))
                                      
            view = await db_session.execute(select_statement)
            view = view.scalars().all()
            
            view_devices_body = []
            
            for record in view:
                device_record = ViewDevicesResponseStruct(device_id=record[0].id,
                                                          name=record[0].name,
                                                          city=record[0].city,
                                                          state=record[0].state,
                                                          owner=record[0].owner,
                                                          device_users=record[1],
                                                          sighting_ids=record[2])
                view_devices_body.append(device_record)
                
            return ViewDevicesResponseSchema(code=200,
                                             message='request handled successfully!',
                                             body=view_devices_body)
    
    
    async def view_species(self, request_data: ViewSpeciesRequestSchema, db_connection: async_sessionmaker) -> ViewSpeciesResponseSchema:
        
        request_data = self.format_query_params(request_data)
        
        async with db_connection() as db_session:
            
            sightings_subquery = select(func.array_agg(Sightings).label("sightings"), Sightings.species_id).group_by(
            Sightings.species_id).subquery()
            
            select_statement = select(Species, 
                                      sightings_subquery.c.sightings) \
                                .join(sightings_subquery, isouter=True)
            
            if request_data.get('species_id', None):
                select_statement = select_statement.where(Species.id.in_(request_data.get('species_id', None)))
            
            view = await db_session.execute(select_statement)
            view = view.scalars().all()
            
            view_species_body = []
            
            for record in view:
                species_record = ViewSpeciesResponseStruct(species_id=record[0].id,
                                                          common_name=record[0].common_name,
                                                          genus=record[0].genus,
                                                          species=record[0].species,
                                                          order=record[0].order,
                                                          wiki_url=record[0].wiki_url,
                                                          sighting_ids=record[1])
                view_species_body.append(species_record)
            
            return ViewSpeciesResponseSchema(code=200,
                                             message='request handled successfully!',
                                             body=view_species_body)
    
    
    async def view_sightnings(self, request_data: ViewSightingsRequestSchema, db_connection: async_sessionmaker) -> ViewSightingsResponseSchema:
        
        request_data = self.format_query_params(request_data)
        
        async with db_connection() as db_session:
            
            select_statement = select(Sightings)
            
            if request_data.get('species_id', None):
                select_statement = select_statement.where(Species.id.in_(request_data.get('species_id', None)))
                
            view = await db_session.execute(select_statement)
            view = view.scalars().all()
            
            view_sightings_body = []
            
            for record in view:
                sighting_record = ViewSightingsResponseStruct(sighting_id=record.id,
                                                            device_id=record.device_id,
                                                            species_id=record.species_id,
                                                            datetime=record.datetime,
                                                            photo_storage_location=record.photo_storage_location,
                                                            weather_conditions=record.weather_conditions,
                                                            feed_type=record.feed_type)
                view_sightings_body.append(sighting_record)
            
            return ViewSightingsResponseSchema(code=200,
                                               message='request handled successfully!',
                                               body=view_sightings_body)