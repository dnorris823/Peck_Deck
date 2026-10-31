"""The backend's side of HLS, fetching the feeder's stream from MediaMTX.

A browser that cannot reach the Pi for WebRTC media plays HLS instead. Every
playlist and segment then comes through the backend, over the same HTTPS origin
as the web app.

The host is the one in the device's stored ``live_url``, which already passed
the private-address check. Only the port and the path differ from WHEP.

MediaMTX tracks each HLS reader. Its first answer to ``index.m3u8`` is a 302
to ``index.m3u8?cookieCheck=1`` with a cookie. A client that comes back without
the cookie gets ``?session=<id>`` on every URI in the playlists instead. The
relay passes the 302 to the browser and drops the cookie, so the session rides
in the query string, which passes through unchanged.
"""
import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from ..config import settings
from .whep import NotStreaming, Refused, auth_headers

logger = logging.getLogger("peckdeck.live")

CONNECT_TIMEOUT_SECONDS = 5.0
# LL-HLS holds a playlist request open until the part it names exists, and the
# first request also waits for MediaMTX to start the encoder. 30 seconds covers
# both, with room to spare.
READ_TIMEOUT_SECONDS = 30.0
CHUNK_BYTES = 64 * 1024

# What MediaMTX serves for one stream: index.m3u8, the media playlists, the
# init segments, the segments and the parts. One file name, no directories. The
# pattern keeps "..", "/" and absolute URLs out of the URL the backend builds.
HLS_FILE = re.compile(r"^[A-Za-z0-9_-]{1,128}\.(m3u8|mp4)$")


def is_playlist(name: str) -> bool:
    return name.endswith(".m3u8")


def hls_url(live_url: str, name: str, query: str) -> str:
    """``http://<live_url host>:<LIVE_HLS_PORT>/feeder/<name>?<query>``."""
    host = urlsplit(live_url).hostname
    return urlunsplit(("http", f"{host}:{settings.LIVE_HLS_PORT}", f"/feeder/{name}", query, ""))


class Moved(Exception):
    """MediaMTX redirected to another file of the same stream."""

    def __init__(self, location: str):
        super().__init__(location)
        # Relative to the relay's own URL: a file name and its query.
        self.location = location


def relative_location(location: str) -> str | None:
    """``index.m3u8?cookieCheck=1`` from ``/feeder/index.m3u8?cookieCheck=1``.

    None for anything but a path to another file of the feeder stream on the
    same server, so the browser is never sent somewhere else.
    """
    parts = urlsplit(location)
    if parts.scheme or parts.netloc or not parts.path.startswith("/feeder/"):
        return None
    name = parts.path[len("/feeder/"):]
    if not HLS_FILE.match(name):
        return None
    return f"{name}?{parts.query}" if parts.query else name


@dataclass
class Upstream:
    """An open MediaMTX response. Iterate ``body()`` to the end, or it leaks."""

    content_type: str
    _http: aiohttp.ClientSession
    _resp: aiohttp.ClientResponse

    async def body(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._resp.content.iter_chunked(CHUNK_BYTES):
                yield chunk
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # The status line has gone out, so the browser sees a cut body.
            logger.warning("HLS body from MediaMTX broke off: %s", exc)
        finally:
            self._resp.release()
            await self._http.close()


async def open_file(live_url: str, name: str, query: str) -> Upstream:
    """GET one HLS file from MediaMTX. The caller streams its body."""
    http = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(
            total=None,
            connect=CONNECT_TIMEOUT_SECONDS,
            sock_read=READ_TIMEOUT_SECONDS,
        )
    )
    try:
        resp = await http.get(
            hls_url(live_url, name, query),
            headers=auth_headers(),
            # A redirect could point the backend at a host the address check
            # never saw.
            allow_redirects=False,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        await http.close()
        raise NotStreaming() from exc
    except BaseException:
        # The browser went away while MediaMTX held the playlist.
        await http.close()
        raise
    if resp.status != 200:
        resp.release()
        await http.close()
        if resp.status == 404:
            raise NotStreaming()
        if resp.status in (301, 302, 303, 307, 308):
            location = relative_location(resp.headers.get("Location", ""))
            if location is not None:
                raise Moved(location)
            logger.warning("MediaMTX redirected HLS somewhere else")
        raise Refused(resp.status)
    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    return Upstream(content_type=content_type, _http=http, _resp=resp)
