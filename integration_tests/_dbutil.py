"""Direct-to-Postgres helpers for the contract tests.

The contract tests drive the *live* servers over HTTP, but still need to set up
throwaway rows and read back results. asyncpg binds connections to the event
loop that opened them, so each helper spins up its own short-lived engine inside
its own ``asyncio.run`` loop rather than reusing the app's global engine.
"""
import asyncio
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import settings
from backend.database.models import Device, Sighting, User


def _run(coro_factory):
    async def _main():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            return await coro_factory(factory)
        finally:
            await engine.dispose()

    return asyncio.run(_main())


def create_throwaway_device(prefix: str = "contract") -> tuple[str, int]:
    """Create a fresh owner + device; return ``(device_token, device_id)``."""
    async def _make(factory) -> tuple[str, int]:
        async with factory() as db:
            async with db.begin():
                u = User(
                    name=f"{prefix} owner",
                    email=f"{prefix}_{secrets.token_hex(4)}@test.dev",
                    password_hash="x", role="owner",
                    notify_email=False, notify_sms=False,
                )
                db.add(u)
                await db.flush()
                token = secrets.token_urlsafe(16)
                dev = Device(name=f"{prefix} device", owner_id=u.id,
                             classification_tier="auto", token=token)
                db.add(dev)
                await db.flush()
                return token, dev.id

    return _run(_make)


def sightings_for_device(device_id: int) -> list[dict]:
    """Return a plain-dict snapshot of every sighting on ``device_id``."""
    async def _query(factory) -> list[dict]:
        async with factory() as db:
            rows = (
                await db.execute(
                    select(Sighting).where(Sighting.device_id == device_id)
                )
            ).scalars().all()
            return [
                {
                    "id": s.id,
                    "confidence_score": s.confidence_score,
                    "classification_tier_used": s.classification_tier_used,
                    "delayed": s.delayed,
                    "has_image": s.image_data is not None,
                    "image_len": len(s.image_data) if s.image_data else 0,
                }
                for s in rows
            ]

    return _run(_query)
