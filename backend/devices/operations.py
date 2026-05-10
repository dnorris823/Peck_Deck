import secrets

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Device, DeviceUser, User


async def get_device(db: AsyncSession, device_id: int) -> Device | None:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


async def get_devices_for_user(db: AsyncSession, user_id: int) -> list[Device]:
    owned = select(Device.id).where(Device.owner_id == user_id)
    member = select(DeviceUser.device_id).where(DeviceUser.user_id == user_id)
    result = await db.execute(
        select(Device).where(or_(Device.id.in_(owned), Device.id.in_(member)))
    )
    return list(result.scalars().all())


async def create_device(
    db: AsyncSession,
    *,
    name: str,
    city: str | None,
    state: str | None,
    owner_id: int,
    classification_tier: str,
    feed_type: str | None,
) -> Device:
    device = Device(
        name=name,
        city=city,
        state=state,
        owner_id=owner_id,
        classification_tier=classification_tier,
        feed_type=feed_type,
        token=secrets.token_urlsafe(32),
    )
    db.add(device)
    await db.flush()
    return device


async def update_device(
    db: AsyncSession,
    device: Device,
    *,
    name: str | None,
    city: str | None,
    state: str | None,
    classification_tier: str | None,
    feed_type: str | None,
) -> Device:
    if name is not None:
        device.name = name
    if city is not None:
        device.city = city
    if state is not None:
        device.state = state
    if classification_tier is not None:
        device.classification_tier = classification_tier
    if feed_type is not None:
        device.feed_type = feed_type
    await db.flush()
    return device


async def add_device_user(db: AsyncSession, device_id: int, user_id: int) -> None:
    existing = await db.execute(
        select(DeviceUser).where(
            DeviceUser.device_id == device_id, DeviceUser.user_id == user_id
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(DeviceUser(device_id=device_id, user_id=user_id))
        await db.flush()


async def remove_device_user(db: AsyncSession, device_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(DeviceUser).where(
            DeviceUser.device_id == device_id, DeviceUser.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
