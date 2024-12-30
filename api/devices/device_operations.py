
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Devices, DeviceUsers
from api.devices.device_schemas import (DevicesCreatorRequestSchema,
                                         DevicesUpdaterRequestSchema,
                                         DevicesDeleterRequestSchema,
                                         DevicesAddUsersRequestSchema,
                                         DevicesRemoveUsersRequestSchema,
                                         DevicesResponseStruct,
                                         DevicesAddUsersResponseStruct,
                                         DevicesResponseSchema,
                                         DevicesAddUsersResponseSchema
                                         )

class DeviceOperations:
    
    async def create_devices(req_data: DevicesCreatorRequestSchema, 
                            db_connection: async_sessionmaker) -> DevicesResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            new_devices_list = []
            new_device_users_list = []

            for record in req_data.get('records_list'):

                new_device = Devices(**record)
                new_devices_list.append(new_device)

            session.add_all(new_devices_list)
            await session.commit()
            
            for new_device in new_devices_list:
                new_device_user = DeviceUsers(device_id=new_device.id, user_id=new_device.owner)
                new_device_users_list.append(new_device_user)
                
            session.add_all(new_device_users_list)
            await session.commit()  
            
            new_devices_body = [DevicesResponseStruct(device_id=new_device[0].id, 
                                                      name=new_device[0].name, 
                                                      city=new_device[0].city, 
                                                      state=new_device[0].state, 
                                                      owner=new_device[0].owner,
                                                      device_user_id=new_device[1].id) for new_device in zip(new_devices_list, new_device_users_list)]

            return DevicesResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=new_devices_body)
            
    async def update_devices(req_data: DevicesUpdaterRequestSchema, 
                            db_connection: async_sessionmaker) -> DevicesResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:
            
            updated_devices_list = []
            
            for record in req_data.get('records_list'):
                updated_device = await session.execute(select(Devices).where(Devices.id == record.get("device_id")))
                updated_device = updated_device.scalar_one()

                # go through all optional items in request and update devices if present
                for k, v in record.items():
                    if k != 'devices_id' and v is not None:
                        setattr(updated_device, k, v)

                updated_devices_list.append(updated_device)

            await session.commit()
            
            updated_devices_body = [DevicesResponseStruct(device_id=updated_device.id, 
                                                      name=updated_device.name, 
                                                      city=updated_device.city, 
                                                      state=updated_device.state, 
                                                      owner=updated_device.owner) for updated_device in updated_devices_list]

            return DevicesResponseSchema(code=200,
                                        message='request handled successfully!',
                                        body=updated_devices_body)
            
    async def delete_devices(req_data: DevicesDeleterRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            for record in req_data.get('records_list'):
                # create devices instance of row from database table devicess with specified device_id
                devices = await session.execute(select(Devices).where(Devices.id == record.get("device_id")))
                devices = devices.scalar_one()

                await session.delete(devices)

            await session.commit()

            return None 
    
    async def add_users_to_device(req_data: DevicesAddUsersRequestSchema, db_connection: async_sessionmaker) -> DevicesAddUsersResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection() as session:
            
            new_device_users_list = []

            for record in req_data.get('records_list'):

                new_device_user = DeviceUsers(**record)
                new_device_users_list.append(new_device_user)

            session.add_all(new_device_users_list)
            await session.commit()
            
            new_device_users_body = [DevicesAddUsersResponseStruct(device_user_id=new_device_user.id, 
                                                                device_id=new_device_user.device_id, 
                                                                user_id=new_device_user.user_id) for new_device_user in new_device_users_list]


            return DevicesAddUsersResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=new_device_users_body)
            
    async def remove_users_from_device(req_data: DevicesRemoveUsersRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection() as session:

            for record in req_data.get('records_list'):
                # create devices instance of row from database table devicess with specified device_id
                device_user = await session.execute(select(DeviceUsers).where(DeviceUsers.id == record.get("device_user_id")))
                device_user = device_user.scalar_one()

                await session.delete(device_user)

            await session.commit()

            return None 