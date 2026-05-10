import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_session_factory
from ..database.models import Device, DeviceUser, Sighting, Species, User
from .email_sender import send_email
from .sms_sender import send_sms

logger = logging.getLogger(__name__)


@dataclass
class NotificationService:
    min_interval_seconds: int = 60
    _last_notified: dict[int, float] = field(default_factory=dict)

    def _can_notify(self, device_id: int) -> bool:
        last = self._last_notified.get(device_id, 0.0)
        return time.monotonic() - last >= self.min_interval_seconds

    def _mark_notified(self, device_id: int) -> None:
        self._last_notified[device_id] = time.monotonic()

    async def dispatch(self, sighting_id: int, device_id: int) -> None:
        """Fire-and-forget entry point — open our own session so the request session lifecycle is irrelevant."""
        if not self._can_notify(device_id):
            logger.debug("Notification throttled for device %d", device_id)
            return

        try:
            async with get_session_factory()() as db:
                async with db.begin():
                    await self._send(db, sighting_id, device_id)
        except Exception:
            logger.exception("Notification dispatch failed for sighting %d", sighting_id)

    async def _send(self, db: AsyncSession, sighting_id: int, device_id: int) -> None:
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

        sighting_count: int = (
            await db.execute(
                select(func.count()).where(
                    Sighting.device_id == device_id,
                    Sighting.species_id == sighting.species_id,
                )
            )
        ).scalar_one()

        # Collect all recipients: device owner + added members (deduped)
        owner = (
            await db.execute(select(User).where(User.id == device.owner_id))
        ).scalar_one_or_none()

        member_rows = (
            await db.execute(
                select(User)
                .join(DeviceUser, User.id == DeviceUser.user_id)
                .where(DeviceUser.device_id == device_id)
            )
        ).scalars().all()

        seen_ids: set[int] = set()
        users: list[User] = []
        for u in ([owner] if owner else []) + list(member_rows):
            if u.id not in seen_ids:
                seen_ids.add(u.id)
                users.append(u)

        if not users:
            return

        self._mark_notified(device_id)

        location = " — ".join(filter(None, [device.city, device.state])) or "Unknown location"
        delayed_note = " (delayed sync)" if sighting.delayed else ""

        tasks = []
        for user in users:
            if user.notify_email and user.email:
                tasks.append(
                    self._email(user, sighting, species, device, sighting_count, location, delayed_note)
                )
            if user.notify_sms and user.phone:
                tasks.append(
                    self._sms(user, sighting, species, device, sighting_count, delayed_note)
                )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("Notification subtask failed: %s", r)

    async def _email(
        self, user: User, sighting: Sighting, species: Species,
        device: Device, count: int, location: str, delayed_note: str,
    ) -> None:
        wiki_url = species.wiki_url or ""
        wiki_link = f'<a href="{wiki_url}">Wikipedia</a>' if wiki_url else "Wikipedia (link pending)"
        sci_name = f"{species.genus} {species.species_name}".strip()

        subject = f"Peck Deck: {species.common_name} spotted at {device.name}!"
        html = (
            f"<html><body>"
            f"<h2>{species.common_name} spotted!</h2>"
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

    async def _sms(
        self, user: User, sighting: Sighting, species: Species,
        device: Device, count: int, delayed_note: str,
    ) -> None:
        wiki_part = f" {species.wiki_url}" if species.wiki_url else ""
        body = (
            f"Peck Deck: {species.common_name} at {device.name}"
            f" — sighting #{count}{delayed_note}.{wiki_part}"
        )
        await send_sms(to_number=user.phone, body=body)


from ..config import settings as _settings

notification_service = NotificationService(
    min_interval_seconds=_settings.NOTIFICATION_MIN_INTERVAL_SECONDS
)
