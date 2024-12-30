
import os
from collections.abc import AsyncIterator

from litestar import Litestar
from litestar.testing import AsyncTestClient

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import pytest_asyncio

from passlib.context import CryptContext

from api.main import app
from database.models import Base, Users

@pytest_asyncio.fixture(scope='function', autouse=True)
async def init_db():
    """Create a test db in the in memory sqlite database"""
    
    # Delete the database file if it exists
    if os.path.exists("api/tests/test_db.db"):
        os.remove("api/tests/test_db.db")
    
    # Create an async engine
    engine = create_async_engine("sqlite+aiosqlite:///api/tests/test_db.db")

    # Create the tables in the database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Create a sessionmaker bound to the async engine
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    
    async with async_session() as session:
        
        # Initialize Passlib CryptContext with Argon2
        pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
        
        user_dict = {'email': 'test@peckdeck.com', 
                     'password': pwd_context.hash('test123')}
        
        new_user = Users(**user_dict)
        session.add(new_user)
        await session.commit()
        
        yield async_session
        
@pytest_asyncio.fixture(scope='function', autouse=True)
async def set_env_vars():
    os.environ['JWT_SECRET'] = 'test_secret'
    os.environ['TESTING'] = "True"
    
    
@pytest_asyncio.fixture(scope='function', autouse=True)
async def test_client(set_env_vars) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app=app) as client:
        yield client
        
