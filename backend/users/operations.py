from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_utils import hash_password, verify_password
from ..database.models import User


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.name))
    return list(result.scalars().all())


async def create_user(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
    phone: str | None,
    role: str,
) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        phone=phone,
        role=role,
        notify_email=True,
        notify_sms=False,
    )
    db.add(user)
    await db.flush()
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    name: str | None,
    phone: str | None,
    notify_email: bool | None,
    notify_sms: bool | None,
) -> User:
    if name is not None:
        user.name = name
    if phone is not None:
        user.phone = phone
    if notify_email is not None:
        user.notify_email = notify_email
    if notify_sms is not None:
        user.notify_sms = notify_sms
    await db.flush()
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.flush()


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
