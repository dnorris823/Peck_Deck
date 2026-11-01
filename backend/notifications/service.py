import asyncio
import logging
import time
from dataclasses import dataclass, field
from html import escape

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_session_factory
from ..database.models import (
    Device,
    DeviceUser,
    PushSubscription,
    Sighting,
    Species,
    User,
    UserPreferences,
)
from ..animals.groups import alert_on, alert_title
from ..species.operations import BIRD
from . import new_species
from .email_sender import send_email
from .push import delete_endpoints, subscriptions_for_users, to_target
from .push_sender import push_enabled, send_push

logger = logging.getLogger(__name__)

# animal_quiet_interval_seconds for a user with no preferences row.
DEFAULT_ANIMAL_INTERVAL = 1800


@dataclass
class NotificationService:
    """Dispatches sighting notifications, honoring each recipient's preferences.

    Throttling is per (recipient, device) using each user's
    ``quiet_interval_seconds`` preference (falling back to
    ``min_interval_seconds`` when a user has no preferences row). The throttle
    map is **in-memory**, so it resets when the API process restarts — a fresh
    burst of notifications can slip through right after a restart. That's an
    acceptable trade-off for anti-spam (we never over-suppress); persisting it
    would need a table and a write on every send.
    """

    min_interval_seconds: int = 60
    # Keyed by (user_id, device_id) — throttle each recipient independently
    # rather than muting an entire feeder after one recipient is notified.
    _last_notified: dict[tuple[int, int], float] = field(default_factory=dict)
    # The animal throttle, keyed by (user_id, device_id, group). Separate from
    # the bird one, so a squirrel that comes back every few minutes sends one
    # push per animal_quiet_interval_seconds and never mutes a bird alert.
    _last_animal: dict[tuple[int, int, str], float] = field(default_factory=dict)

    def _can_notify(self, user_id: int, device_id: int, interval: int) -> bool:
        last = self._last_notified.get((user_id, device_id))
        # A recipient we've never notified is always eligible. Defaulting `last`
        # to 0.0 here used to mean "throttled until time.monotonic() >= interval"
        # — and on Linux time.monotonic() counts from boot, so for the first
        # `interval` seconds of uptime *every* first notification was silently
        # suppressed. That dropped the first sighting after any reboot, and made
        # the notification tests fail intermittently on freshly-booted CI runners.
        if last is None:
            return True
        return time.monotonic() - last >= interval

    def _mark_notified(self, user_id: int, device_id: int) -> None:
        self._last_notified[(user_id, device_id)] = time.monotonic()

    def _can_notify_animal(self, key: tuple[int, int, str], interval: int) -> bool:
        last = self._last_animal.get(key)
        return last is None or time.monotonic() - last >= interval

    async def dispatch(
        self, sighting_id: int, device_id: int, *, after_recheck: bool = False
    ) -> None:
        """Fire-and-forget entry point — open our own session so the request session lifecycle is irrelevant.

        ``after_recheck`` is the Tier 2 re-check's call. It sends the new
        species alert only, because the upload already sent the normal one.
        """
        try:
            async with get_session_factory()() as db:
                async with db.begin():
                    await self._send(db, sighting_id, device_id, after_recheck=after_recheck)
        except Exception:
            logger.exception("Notification dispatch failed for sighting %d", sighting_id)

    async def _send(
        self, db: AsyncSession, sighting_id: int, device_id: int, *, after_recheck: bool = False
    ) -> None:
        sighting = (
            await db.execute(select(Sighting).where(Sighting.id == sighting_id))
        ).scalar_one_or_none()
        if sighting is None:
            return

        species = (
            await db.execute(select(Species).where(Species.id == sighting.species_id))
        ).scalar_one_or_none()
        device = (
            await db.execute(select(Device).where(Device.id == device_id))
        ).scalar_one_or_none()

        if species is None or device is None:
            return

        # An animal visit sends no bird alert. It must not count as a "new
        # species" or start the bird throttle, so a squirrel never mutes the
        # cardinal that lands after it. It gets its own per-group push. An
        # animal the re-check found sends nothing.
        if species.kind != BIRD:
            if not after_recheck:
                await self._send_animal(db, sighting, species, device)
            return

        sighting_count: int = (
            await db.execute(
                select(func.count()).where(
                    Sighting.device_id == device_id,
                    Sighting.species_id == sighting.species_id,
                )
            )
        ).scalar_one()

        users = await _recipients(db, device)
        if not users:
            return
        seen_ids = {u.id for u in users}

        # Load each recipient's preferences in one query (missing rows → defaults).
        prefs_rows = (
            await db.execute(
                select(UserPreferences).where(UserPreferences.user_id.in_(seen_ids))
            )
        ).scalars().all()
        prefs_by_user = {p.user_id: p for p in prefs_rows}

        # Push subscriptions for every recipient, in one query and *before* any
        # sending starts. Loading them lazily inside the per-recipient coroutines
        # would have several of them using this AsyncSession concurrently, which
        # it does not support.
        subs_by_user = (
            await subscriptions_for_users(db, seen_ids) if push_enabled() else {}
        )
        # Endpoints the push service reported as permanently gone; deleted after
        # all sends finish so a dead browser isn't retried on every sighting.
        dead_endpoints: list[str] = []

        location = " — ".join(filter(None, [device.city, device.state])) or "Unknown location"
        delayed_note = " (delayed sync)" if sighting.delayed else ""
        # A sighting waiting for the re-check decides "new" after it, in the
        # re-check's own dispatch.
        decide_new = after_recheck or not new_species.waits_for_recheck(sighting)

        tasks = []
        for user in users:
            prefs = prefs_by_user.get(user.id)
            kind = (
                await new_species.new_kind(db, sighting, species, user.id)
                if decide_new else None
            )
            if new_species.wanted(kind, prefs, sighting.confidence_score):
                # The new species alert takes the place of the normal one. It
                # skips the throttle and does not start it.
                title = new_species.headline(kind, species.common_name, device.name)
                tasks.extend(
                    self._channels(
                        user, subs_by_user, sighting, species, device, sighting_count,
                        location, delayed_note, dead_endpoints, headline=title,
                    )
                )
                continue
            if after_recheck:
                continue
            # "Only new species" mutes the normal alerts.
            if prefs is not None and prefs.notify_new_species_only:
                logger.debug("Skipping user %d: only new species", user.id)
                continue

            # Per-recipient throttle using this user's quiet interval.
            interval = prefs.quiet_interval_seconds if prefs is not None else self.min_interval_seconds
            if not self._can_notify(user.id, device_id, interval):
                logger.debug("Notification throttled for user %d on device %d", user.id, device_id)
                continue

            channels = self._channels(
                user, subs_by_user, sighting, species, device, sighting_count,
                location, delayed_note, dead_endpoints,
            )
            if channels:
                self._mark_notified(user.id, device_id)
                tasks.extend(channels)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("Notification subtask failed: %s", r)

        if dead_endpoints:
            removed = await delete_endpoints(db, dead_endpoints)
            logger.info("Pruned %d dead push subscription(s)", removed)

    def _channels(
        self, user: User, subs_by_user: dict, sighting: Sighting, species: Species,
        device: Device, count: int, location: str, delayed_note: str,
        dead_endpoints: list[str], *, headline: str | None = None,
    ) -> list:
        """One coroutine per channel the user receives sighting alerts on."""
        channels = []
        if user.notify_email and user.email:
            channels.append(
                self._email(
                    user, sighting, species, device, count, location, delayed_note,
                    headline=headline,
                )
            )
        # Web push needs no per-user flag: a stored subscription *is* the
        # opt-in, and unsubscribing in the browser deletes the row.
        for sub in subs_by_user.get(user.id, []):
            channels.append(
                self._push(
                    sub, sighting, species, device, count,
                    location, delayed_note, dead_endpoints, headline=headline,
                )
            )
        return channels

    async def _send_animal(
        self, db: AsyncSession, sighting: Sighting, species: Species, device: Device
    ) -> None:
        """Push an animal visit to each recipient who has its group switched on.

        Push only, never email. Throttled per (user, feeder, group) by
        animal_quiet_interval_seconds. The tag is per feeder and group, so a
        repeat replaces the last alert on the phone instead of stacking.
        """
        group = species.animal_group
        if group is None or not push_enabled():
            return
        users = await _recipients(db, device)
        if not users:
            return
        ids = {u.id for u in users}
        prefs_by_user = {
            p.user_id: p
            for p in (
                await db.execute(select(UserPreferences).where(UserPreferences.user_id.in_(ids)))
            ).scalars()
        }
        subs_by_user = await subscriptions_for_users(db, ids)

        location = " — ".join(filter(None, [device.city, device.state])) or "Unknown location"
        delayed_note = " (delayed sync)" if sighting.delayed else ""
        payload = {
            "title": alert_title(group, device.name),
            "body": (
                f"{species.common_name} · {round(sighting.confidence_score * 100)}% confident"
                f" · {location}{delayed_note}"
            ),
            "tag": f"peckdeck-device-{device.id}-animal-{group}",
            "data": {
                "sighting_id": sighting.id,
                "species_id": species.id,
                "device_id": device.id,
                "url": f"/?sighting={sighting.id}",
            },
        }

        sends = []
        for user in users:
            prefs = prefs_by_user.get(user.id)
            if not alert_on(prefs.animal_alerts if prefs else None, group):
                continue
            subs = subs_by_user.get(user.id, [])
            if not subs:
                continue
            key = (user.id, device.id, group)
            interval = prefs.animal_quiet_interval_seconds if prefs else DEFAULT_ANIMAL_INTERVAL
            if not self._can_notify_animal(key, interval):
                logger.debug("Animal push throttled for user %d, device %d, %s", *key)
                continue
            self._last_animal[key] = time.monotonic()
            sends.extend((sub, send_push(to_target(sub), payload)) for sub in subs)

        if not sends:
            return
        results = await asyncio.gather(*(c for _, c in sends), return_exceptions=True)
        dead = []
        for (sub, _), result in zip(sends, results):
            if isinstance(result, Exception):
                logger.warning("Animal push failed: %s", result)
            elif result.gone:
                dead.append(sub.endpoint)
        if dead:
            await delete_endpoints(db, dead)

    async def _email(
        self, user: User, sighting: Sighting, species: Species,
        device: Device, count: int, location: str, delayed_note: str,
        *, headline: str | None = None,
    ) -> None:
        wiki_url = species.wiki_url or ""
        wiki_link = f'<a href="{wiki_url}">Wikipedia</a>' if wiki_url else "Wikipedia (link pending)"
        sci_name = f"{species.genus} {species.species_name}".strip()

        subject = "Peck Deck: " + (headline or f"{species.common_name} spotted at {device.name}!")
        html = (
            f"<html><body>"
            f"<h2>{headline or species.common_name + ' spotted!'}</h2>"
            f"<p><strong>{species.common_name}</strong> (<em>{sci_name}</em>)</p>"
            f"<p>Device: <strong>{device.name}</strong> — {location}{delayed_note}</p>"
            f"<p>Confidence: {sighting.confidence_score:.0%} | Tier: {sighting.classification_tier_used}</p>"
            f"<p>Sighting #{count} at this feeder</p>"
            f"<p>{wiki_link}</p>"
            + (
                "<img src='cid:sighting_image' style='max-width:600px;border-radius:8px'>"
                if sighting.image_data
                else ""
            )
            + "</body></html>"
        )
        await send_email(
            to_email=user.email,
            subject=subject,
            html_body=html,
            image_data=sighting.image_data,
            image_filename=f"sighting_{sighting.id}.jpg",
        )

    async def _push(
        self, sub: PushSubscription, sighting: Sighting, species: Species,
        device: Device, count: int, location: str, delayed_note: str,
        dead_endpoints: list[str], *, headline: str | None = None,
    ) -> None:
        """Send one web push and record the endpoint if it is permanently gone.

        The payload is what the service worker renders, so it carries display
        text rather than ids to look up — the worker has no session and cannot
        call the API. ``tag`` lets a phone that missed several alerts collapse
        them into the latest one per feeder instead of stacking a wall of them.
        A new species alert, with a ``headline``, has a tag of its own, so a
        normal alert from the same feeder never replaces it.
        """
        payload = {
            "title": headline or f"{species.common_name} at {device.name}",
            "body": (
                f"{round(sighting.confidence_score * 100)}% confident · "
                f"sighting #{count} · {location}{delayed_note}"
            ),
            "tag": (
                f"peckdeck-new-species-{sighting.id}" if headline
                else f"peckdeck-device-{device.id}"
            ),
            "data": {
                "sighting_id": sighting.id,
                "species_id": species.id,
                "device_id": device.id,
                # The web app opens the detail view for ?sighting=<id>.
                "url": f"/?sighting={sighting.id}",
            },
        }
        result = await send_push(to_target(sub), payload)
        if result.gone:
            dead_endpoints.append(sub.endpoint)



async def _recipients(db: AsyncSession, device: Device) -> list[User]:
    """The feeder's owner and members, owner first, each once."""
    owner = (
        await db.execute(select(User).where(User.id == device.owner_id))
    ).scalar_one_or_none()
    members = (
        await db.execute(
            select(User)
            .join(DeviceUser, User.id == DeviceUser.user_id)
            .where(DeviceUser.device_id == device.id)
        )
    ).scalars().all()
    seen: set[int] = set()
    users: list[User] = []
    for u in ([owner] if owner else []) + list(members):
        if u.id not in seen:
            seen.add(u.id)
            users.append(u)
    return users


async def send_feed_alert(device_id: int, title: str, body: str) -> None:
    """Tell the feeder's owner that its feed is low or out.

    Owner only, on the same email and push channels as a sighting. Not
    throttled, because the feed monitor sends one alert per spell. Opens its
    own session like ``dispatch`` and never raises.
    """
    try:
        async with get_session_factory()() as db:
            async with db.begin():
                await _send_feed_alert(db, device_id, title, body)
    except Exception:
        logger.exception("Feed alert failed for device %d", device_id)


async def _send_feed_alert(db: AsyncSession, device_id: int, title: str, body: str) -> None:
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if device is None:
        return
    owner = (await db.execute(select(User).where(User.id == device.owner_id))).scalar_one_or_none()
    if owner is None:
        return
    subs = (await subscriptions_for_users(db, {owner.id}) if push_enabled() else {}).get(owner.id, [])

    tasks = []
    if owner.notify_email and owner.email:
        html = (
            f"<html><body><h2>{escape(title)}</h2><p>{escape(body)}</p>"
            "<p>Tap Refilled on the feeder's card once it is full again.</p></body></html>"
        )
        tasks.append(send_email(to_email=owner.email, subject=f"Peck Deck: {title}", html_body=html))
    payload = {
        "title": title,
        "body": body,
        # One feed alert per feeder on the lock screen, apart from sightings.
        "tag": f"peckdeck-feed-{device.id}",
        "data": {"device_id": device.id, "url": "/?screen=feeders"},
    }
    tasks.extend(send_push(to_target(sub), payload) for sub in subs)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    dead = []
    for sub, result in zip(subs, results[len(tasks) - len(subs):]):
        if isinstance(result, Exception):
            logger.warning("Feed alert push failed: %s", result)
        elif result.gone:
            dead.append(sub.endpoint)
    if dead:
        await delete_endpoints(db, dead)


from ..config import settings as _settings

notification_service = NotificationService(
    min_interval_seconds=_settings.NOTIFICATION_MIN_INTERVAL_SECONDS
)
