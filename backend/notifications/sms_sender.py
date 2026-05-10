import logging

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


async def send_sms(*, to_number: str, body: str) -> bool:
    if not (
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_FROM_NUMBER
    ):
        logger.debug("Twilio not configured — skipping SMS to %s", to_number)
        return False

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data={
                    "From": settings.TWILIO_FROM_NUMBER,
                    "To": to_number,
                    "Body": body,
                },
                auth=aiohttp.BasicAuth(
                    settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
                ),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status not in (200, 201):
                    body_text = await resp.text()
                    logger.warning("Twilio %d for %s: %s", resp.status, to_number, body_text[:200])
                    return False
                return True
    except Exception:
        logger.exception("Failed to send SMS to %s", to_number)
        return False
