"""The backend's side of WHEP, talking to the feeder's MediaMTX.

Only signaling passes through here: one offer, one answer, one hang-up. Media
flows directly between the browser and the Pi.

The relay keeps no session table. The session id is the last path segment of
MediaMTX's ``Location`` header, and the session URL is rebuilt from the
device's ``live_url`` on DELETE. A restart or a second API process loses
nothing.
"""
import asyncio
import base64
import logging
import re
from urllib.parse import urlsplit

import aiohttp

from ..config import settings

logger = logging.getLogger("peckdeck.live")

# MediaMTX starts the encoder on demand, and the first offer waits for it.
OFFER_TIMEOUT_SECONDS = 15.0
HANGUP_TIMEOUT_SECONDS = 5.0

# MediaMTX session ids are UUIDs. The pattern also keeps "..", "/", and "?" out
# of the session URL the backend builds.
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class NotStreaming(Exception):
    """MediaMTX did not answer, timed out, or has no such stream or session."""


class Refused(Exception):
    """MediaMTX answered with something other than success."""

    def __init__(self, status: int):
        super().__init__(f"MediaMTX returned HTTP {status}")
        self.status = status


def auth_headers() -> dict[str, str]:
    """Basic auth for the MediaMTX read user, or nothing if none is set."""
    if not settings.LIVE_READ_USER:
        return {}
    pair = f"{settings.LIVE_READ_USER}:{settings.LIVE_READ_PASSWORD}".encode()
    return {"Authorization": "Basic " + base64.b64encode(pair).decode("ascii")}


def session_url(live_url: str, session: str) -> str:
    """The MediaMTX URL of one session: ``<live_url>/<session>``."""
    return live_url.rstrip("/") + "/" + session


def _session_from_location(location: str) -> str | None:
    tail = urlsplit(location).path.rstrip("/").rsplit("/", 1)[-1]
    return tail if SESSION_ID.match(tail) else None


async def post_offer(live_url: str, offer: bytes) -> tuple[bytes, str]:
    """Send a browser's SDP offer. Returns the SDP answer and the session id."""
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                live_url,
                data=offer,
                headers={"Content-Type": "application/sdp", **auth_headers()},
                # A redirect could point the backend at a host the address
                # check never saw.
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=OFFER_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status == 404:
                    raise NotStreaming()
                if resp.status != 201:
                    raise Refused(resp.status)
                session = _session_from_location(resp.headers.get("Location", ""))
                if session is None:
                    logger.warning("MediaMTX answered with no usable Location header")
                    raise Refused(resp.status)
                return await resp.read(), session
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise NotStreaming() from exc


async def delete_session(live_url: str, session: str) -> None:
    """End one session on MediaMTX."""
    try:
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                session_url(live_url, session),
                headers=auth_headers(),
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=HANGUP_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status == 404:
                    raise NotStreaming()
                if not 200 <= resp.status < 300:
                    raise Refused(resp.status)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise NotStreaming() from exc
