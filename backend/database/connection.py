from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(url: str) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _session_factory


async def create_tables() -> None:
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables. Used by the integration suite to reset a real
    Postgres database to a clean, deterministic state before seeding."""
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def dispose_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def provide_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        async with session.begin():
            yield session
