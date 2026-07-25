"""Push subscription storage — FLEDGE Phase 7.

Thin data-access layer over ``push_subscriptions``. Kept separate from
``push_sender`` so the transport (crypto + HTTP) has no database dependency and
can be unit-tested on its own.
"""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import PushSubscription
from .push_sender import PushTarget


async def upsert_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    """Store a browser's subscription, replacing any previous row for it.

    The endpoint identifies the browser installation, so a re-subscribe (new
    VAPID key, permission re-granted, another account signing in on the same
    browser) must *take over* the existing row. Inserting instead would either
    violate the unique constraint or — if the constraint were dropped — deliver
    every alert twice.
    """
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        existing.created_at = datetime.now(timezone.utc)
        await db.flush()
        return existing

    sub = PushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
        created_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    await db.flush()
    return sub


async def list_subscriptions(
    db: AsyncSession, user_id: int
) -> list[PushSubscription]:
    result = await db.execute(
        select(PushSubscription)
        .where(PushSubscription.user_id == user_id)
        .order_by(PushSubscription.created_at.desc())
    )
    return list(result.scalars().all())


async def subscriptions_for_users(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, list[PushSubscription]]:
    """All subscriptions for a set of recipients, grouped by user.

    Loaded in one query by the notification service *before* it starts sending,
    so concurrent per-recipient sends never touch the shared session.
    """
    if not user_ids:
        return {}
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
    )
    grouped: dict[int, list[PushSubscription]] = {}
    for sub in result.scalars().all():
        grouped.setdefault(sub.user_id, []).append(sub)
    return grouped


async def delete_subscription(
    db: AsyncSession, *, user_id: int, endpoint: str
) -> bool:
    """Remove one of *this user's* subscriptions. Returns whether a row went."""
    result = await db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
    )
    await db.flush()
    return (result.rowcount or 0) > 0


async def delete_endpoints(db: AsyncSession, endpoints: list[str]) -> int:
    """Drop subscriptions the push service reported as gone (404/410).

    Not scoped to a user: this is called from the notification dispatcher on
    endpoints it just read out of the table, and a dead endpoint is dead for
    whoever owns it.
    """
    if not endpoints:
        return 0
    result = await db.execute(
        delete(PushSubscription).where(PushSubscription.endpoint.in_(endpoints))
    )
    await db.flush()
    return result.rowcount or 0


def to_target(sub: PushSubscription) -> PushTarget:
    return PushTarget(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth)
