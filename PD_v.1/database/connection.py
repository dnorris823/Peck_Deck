
import os

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

async def connect_to_db(): 
    
    if os.getenv("TESTING") == "True":
        print('USING TESTING CONNECTION_STRING')
        connection_string = "sqlite+aiosqlite:///api/tests/test_db.db"
        # Create an async engine
        engine = create_async_engine(connection_string, echo=True)
    else:
        # Create an async engine
        connection_string = "sqlite+aiosqlite:///database/peck_deck.db"
        engine = create_async_engine(connection_string, echo=True)

    # create sessionmaker
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
