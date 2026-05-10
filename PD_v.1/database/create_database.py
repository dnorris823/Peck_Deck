import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from database.models import Base
from api.users.user_operations import UserOperations
from api.users.user_schemas import UsersCreatorRequestSchema, UsersCreatorStruct


async def init_db():
    
    DATABASE_URL = "sqlite+aiosqlite:///database/peck_deck.db"

    # Create an async engine
    engine = create_async_engine(DATABASE_URL, echo=True)

    # Create a sessionmaker bound to the async engine
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    # Create the tables in the database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    print('CREATING DEFAULT USER')    
        
    user_ops = UserOperations()
    response = await user_ops.create_users(req_data=UsersCreatorRequestSchema(records_list=[UsersCreatorStruct(email='test@peck_deck.com', password='test123')]), 
                                db_connection=async_session)
    print(response)

# Run the initialization function
asyncio.run(init_db())
