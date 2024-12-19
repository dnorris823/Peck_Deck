
from litestar.exceptions import NotAuthorizedException

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from passlib.context import CryptContext

from database.models import Users
from api.users.user_schemas import (UsersCreatorRequestSchema,
                                    UsersUpdaterRequestSchema,
                                    UsersDeleterRequestSchema,
                                    UsersResponseStruct,
                                    UsersResponseSchema,)

class UserOperations:
    
    # Initialize Passlib CryptContext with Argon2
    pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

    async def create_users(self, req_data: UsersCreatorRequestSchema, 
                        db_connection: async_sessionmaker) -> UsersResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:

            new_users_list = []

            for record in req_data.get('records_list'):
                
                record['password'] = self.pwd_context.hash(record.get('password'))

                new_user = Users(**record)
                new_users_list.append(new_user)

            session.add_all(new_users_list)
            await session.commit()

            return UsersResponseSchema(code=201,
                                    message='request handled successfully!',
                                    body=[UsersResponseStruct({'user_id': new_user.id, 'email': new_user.email}) for new_user in new_users_list])
            
    async def update_users(self, req_data: UsersUpdaterRequestSchema, 
                        db_connection: async_sessionmaker) -> UsersResponseSchema:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:
            
            updated_users_list = []
            
            for record in req_data.get('records_list'):
                updated_users = await session.execute(select(Users).where(Users.id == record.get("users_id")))
                updated_users = updated_users.scalar_one()

                # go through all optional items in request and update users if present
                for k, v in record.items():
                    if k != 'users_id':
                        if k == 'password':
                            v = self.pwd_context.hash(v)
                        setattr(updated_users, k, v)

                updated_users_list.append(updated_users)

            await session.commit()

            return UsersResponseSchema(code=200,
                                    message='request handled successfully!',
                                    body=[UsersResponseStruct({'user_id': updated_user.id, 'email': updated_user.email}) for updated_user in updated_users_list])
            
    async def delete_users(req_data: UsersDeleterRequestSchema, db_connection: async_sessionmaker) -> None:

        req_data = req_data.model_dump()

        async with db_connection.async_session() as session:

            for record in req_data.get('records_list'):
                # create users instance of row from database table userss with specified users_id
                users = await session.execute(select(Users).where(Users.id == record.get("users_id")))
                users = users.scalar_one()

                await session.delete(users)

            await session.commit()

            return None    
        
            