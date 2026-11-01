from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.jwt_utils import hash_password, verify_password
from ..database.models import (
    Device,
    DeviceUser,
    FeederRefill,
    PushSubscription,
    Sighting,
    User,
    UserPreferences,
)


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


async def revoke_tokens(db: AsyncSession, user: User) -> User:
    """Invalidate every JWT issued to the user. The guard checks the version."""
    user.token_version = (user.token_version or 0) + 1
    await db.flush()
    return user


async def set_role(db: AsyncSession, user: User, role: str) -> User:
    user.role = role
    await db.flush()
    return user


async def is_last_owner(db: AsyncSession, user: User) -> bool:
    """Whether the user is the only owner left.

    The row lock makes a second demotion or delete wait for this transaction,
    so two owners cannot each remove the other. SQLite ignores it.
    """
    if user.role != "owner":
        return False
    owners = (
        await db.execute(select(User.id).where(User.role == "owner").with_for_update())
    ).scalars().all()
    return list(owners) == [user.id]


async def owned_device_names(db: AsyncSession, user_id: int) -> list[str]:
    result = await db.execute(
        select(Device.name).where(Device.owner_id == user_id).order_by(Device.name)
    )
    return list(result.scalars().all())


async def delete_user(db: AsyncSession, user: User) -> None:
    """Delete the user and the rows that only matter to them.

    The caller refuses a user who owns a feeder. The feeder's sightings hold
    the only copy of each image, so they must not go with the user. A
    correction the user made keeps its species and loses only its author. So
    does a refill they logged.
    """
    await db.execute(delete(DeviceUser).where(DeviceUser.user_id == user.id))
    await db.execute(delete(UserPreferences).where(UserPreferences.user_id == user.id))
    await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id))
    await db.execute(
        update(Sighting).where(Sighting.corrected_by == user.id).values(corrected_by=None)
    )
    await db.execute(
        update(FeederRefill).where(FeederRefill.user_id == user.id).values(user_id=None)
    )
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
    new_species_alerts: dict[str, bool | None] | None = None,
    animal_alerts: dict[str, bool] | None = None,
    animal_quiet_interval_seconds: int | None = None,
) -> UserPreferences:
    if quiet_interval_seconds is not None:
        prefs.quiet_interval_seconds = quiet_interval_seconds
    if notify_new_species_only is not None:
        prefs.notify_new_species_only = notify_new_species_only
    # notify_first_ever and its siblings. A None leaves the switch alone.
    for name, value in (new_species_alerts or {}).items():
        if value is not None:
            setattr(prefs, name, value)
    if animal_alerts is not None:
        # A new dict, so SQLAlchemy sees the JSON column change.
        prefs.animal_alerts = {**(prefs.animal_alerts or {}), **animal_alerts}
    if animal_quiet_interval_seconds is not None:
        prefs.animal_quiet_interval_seconds = animal_quiet_interval_seconds
    await db.flush()
    return prefs


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
