
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker


def connect_to_db(): 

    # Create an async engine
    engine = create_async_engine("sqlite+aiosqlite:///peck_deck.db", echo=True)

    # create sessionmaker
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
