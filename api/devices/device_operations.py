
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

        async with db_connection.async_session() as session:

            new_devices_list = []

            for record in req_data.get('records_list'):

                new_device = Devices(**record)
                new_devices_list.append(new_device)

            session.add_all(new_devices_list)
            await session.commit()

            return DevicesResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=[DevicesResponseStruct(**new_device.as_dict()) for new_device in new_devices_list])
            
    async def update_devices(req_data: DevicesUpdaterRequestSchema, 
                            db_connection: async_sessionmaker) -> DevicesResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:
            
            updated_devices_list = []
            
            for record in req_data.get('records_list'):
                updated_device = await session.execute(select(Devices).where(Devices.id == record.get("devices_id")))
                updated_device = updated_device.scalar_one()

                # go through all optional items in request and update devices if present
                for k, v in record.items():
                    if k != 'devices_id':
                        setattr(updated_device, k, v)

                updated_devices_list.append(updated_device)

            await session.commit()

            return DevicesResponseSchema(code=200,
                                        message='request handled successfully!',
                                        body=[DevicesResponseStruct(**updated_device.as_dict()) for updated_device in updated_devices_list])
            
    async def delete_devices(req_data: DevicesDeleterRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:

            for record in req_data.get('records_list'):
                # create devices instance of row from database table devicess with specified device_id
                devices = await session.execute(select(Devices).where(Devices.id == record.get("device_id")))
                devices = devices.scalar_one()

                await session.delete(devices)

            await session.commit()

            return None 
    
    async def add_users_to_device(req_data: DevicesAddUsersRequestSchema, db_connection: async_sessionmaker) -> DevicesAddUsersResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:
            
            new_device_users_list = []

            for record in req_data.get('records_list'):

                new_device_user = DeviceUsers(**record)
                new_device_users_list.append(new_device_user)

            session.add_all(new_device_users_list)
            await session.commit()

            return DevicesAddUsersResponseSchema(code=201,
                                        message='request handled successfully!',
                                        body=[DevicesAddUsersResponseStruct(**new_device.as_dict()) for new_device in new_device_users_list])
            
    async def remove_users_from_device(req_data: DevicesRemoveUsersRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:

            for record in req_data.get('records_list'):
                # create devices instance of row from database table devicess with specified device_id
                device_user = await session.execute(select(DeviceUsers).where(DeviceUsers.id == record.get("device_user_id")))
                device_user = device_user.scalar_one()

                await session.delete(device_user)

            await session.commit()

            return None 