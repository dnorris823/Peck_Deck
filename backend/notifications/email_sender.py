import base64
import logging

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


async def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    image_data: bytes | None = None,
    image_filename: str = "sighting.jpg",
    inline_images: list[tuple[str, bytes]] | None = None,
) -> bool:
    """Send one HTML email through SendGrid. Never raises.

    ``image_data`` goes inline as ``cid:sighting_image``. ``inline_images`` adds
    more, each a (content id, JPEG bytes) pair the HTML refers to as ``cid:<id>``.
    """
    if not settings.SENDGRID_API_KEY:
        logger.debug("SendGrid not configured — skipping email to %s", to_email)
        return False

    payload: dict = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": settings.NOTIFICATION_FROM_EMAIL},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }

    images = [(image_filename, "sighting_image", image_data)] if image_data else []
    images += [(f"{cid}.jpg", cid, data) for cid, data in inline_images or []]
    if images:
        payload["attachments"] = [
            {
                "content": base64.b64encode(data).decode(),
                "type": "image/jpeg",
                "filename": filename,
                "disposition": "inline",
                "content_id": cid,
            }
            for filename, cid, data in images
        ]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    logger.warning("SendGrid %d for %s: %s", resp.status, to_email, body[:200])
                    return False
                return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False
