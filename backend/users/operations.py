from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_utils import hash_password, verify_password
from ..database.models import User, UserPreferences


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
    role: str,
) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role,
        notify_email=True,
    )
    db.add(user)
    await db.flush()
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    name: str | None,
    notify_email: bool | None,
    email: str | None = None,
) -> User:
    if name is not None:
        user.name = name
    if notify_email is not None:
        user.notify_email = notify_email
    if email is not None:
        user.email = email
    await db.flush()
    return user


async def set_password(db: AsyncSession, user: User, new_password: str) -> User:
    user.password_hash = hash_password(new_password)
    await db.flush()
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.flush()


async def get_or_create_preferences(db: AsyncSession, user_id: int) -> UserPreferences:
    """Return the user's preferences row, creating one with defaults if absent."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


async def update_preferences(
    db: AsyncSession,
    prefs: UserPreferences,
    *,
    quiet_interval_seconds: int | None,
    notify_new_species_only: bool | None,
) -> UserPreferences:
    if quiet_interval_seconds is not None:
        prefs.quiet_interval_seconds = quiet_interval_seconds
    if notify_new_species_only is not None:
        prefs.notify_new_species_only = notify_new_species_only
    await db.flush()
    return prefs


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
