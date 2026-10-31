"""Relay WebRTC signaling and HLS between the web app and a feeder's MediaMTX.

The web app runs on HTTPS, and a browser on an HTTPS page cannot POST to
``http://<pi>:8889``. Sending the offer here keeps it same-origin and keeps the
JWT and device access rules in force. See docs/live-video.md.

HLS is the fallback for a browser that cannot reach the Pi for WebRTC media.
Its playlists and segments pass through here.

No route takes the ``db`` dependency. It holds a session and a transaction
for the whole request, and the first offer can wait 15 seconds for MediaMTX to
start the encoder. A short session does the lookup and closes before the
upstream call.
"""
import logging
import time
from dataclasses import dataclass

from litestar import Controller, Request, Response, delete, get, post
from litestar.exceptions import HTTPException, NotFoundException
from litestar.datastructures import ResponseHeader
from litestar.openapi.spec import (
    OpenAPIHeader,
    OpenAPIMediaType,
    OpenAPIResponse,
    Operation,
    RequestBody,
    Schema,
)
from litestar.params import FromPath
from litestar.response import Stream

from ..auth.guards import USER_JWT, user_guard
from ..database.connection import get_session_factory
from ..devices.controller import live_available
from ..devices.operations import get_device
from ..sightings.operations import user_can_access_device
from . import hls, whep

logger = logging.getLogger("peckdeck.live")

NOT_STREAMING = "feeder not streaming"


def _not_streaming() -> HTTPException:
    return HTTPException(status_code=503, detail=NOT_STREAMING)


async def _visible_device(request: Request, device_id: int):
    """The device, if this user may see it. 404 otherwise, so ids do not leak."""
    async with get_session_factory()() as db:
        device = await get_device(db, device_id)
        if device is None or not await user_can_access_device(
            db, request.state.user_id, request.state.role, device.id, device.owner_id
        ):
            raise NotFoundException()
        return device


@dataclass
class _SdpOfferOperation(Operation):
    """Documents the raw SDP body. Litestar decodes a ``data`` argument as JSON."""

    def __post_init__(self) -> None:
        self.request_body = RequestBody(
            content={"application/sdp": OpenAPIMediaType(schema=Schema(type="string"))},
            description="SDP offer, sent after ICE gathering completes",
            required=True,
        )


class LiveController(Controller):
    path = "/devices/{device_id:int}/live/whep"
    tags = ["devices"]

    @post(
        "/",
        guards=[user_guard],
        security=USER_JWT,
        status_code=201,
        media_type="application/sdp",
        operation_class=_SdpOfferOperation,
        response_headers=[
            ResponseHeader(
                name="Location",
                description="Session URL, /devices/{device_id}/live/whep/{session}",
                documentation_only=True,
            )
        ],
    )
    async def offer(
        self,
        device_id: FromPath[int],
        request: Request,
        body: bytes,
    ) -> Response[bytes]:
        """Relay a WHEP offer to the feeder. Returns the SDP answer.

        Send the offer after ICE gathering completes. There is no trickle ICE,
        so the session URL in `Location` takes DELETE only. 503 means the feeder
        is not streaming: no live address, offline, or MediaMTX did not answer.
        """
        if request.content_type[0] != "application/sdp":
            raise HTTPException(status_code=415, detail="Content-Type must be application/sdp")
        if not body:
            raise HTTPException(status_code=400, detail="Empty SDP offer")
        device = await _visible_device(request, device_id)
        if not live_available(device):
            raise _not_streaming()
        try:
            answer, session = await whep.post_offer(device.live_url, body)
        except whep.NotStreaming:
            logger.warning("live offer for device %d: MediaMTX not streaming", device_id)
            raise _not_streaming()
        except whep.Refused as exc:
            logger.warning("live offer for device %d: %s", device_id, exc)
            if exc.status == 400:
                raise HTTPException(status_code=400, detail="feeder rejected the offer")
            raise HTTPException(status_code=502, detail="feeder refused the offer")
        logger.info("live session %s opened on device %d", session, device_id)
        return Response(
            content=answer,
            status_code=201,
            media_type="application/sdp",
            headers={"Location": f"/devices/{device_id}/live/whep/{session}"},
        )

    @delete("/{session:str}", guards=[user_guard], security=USER_JWT, status_code=204)
    async def hang_up(
        self, device_id: FromPath[int], session: FromPath[str], request: Request
    ) -> None:
        """End a live session. The path is the `Location` from the offer."""
        if not whep.SESSION_ID.match(session):
            raise NotFoundException()
        device = await _visible_device(request, device_id)
        if device.live_url is None:
            raise _not_streaming()
        try:
            await whep.delete_session(device.live_url, session)
        except whep.NotStreaming:
            raise _not_streaming()
        except whep.Refused as exc:
            logger.warning("live hang-up on device %d: %s", device_id, exc)
            raise HTTPException(status_code=502, detail="feeder refused the hang-up")
        logger.info("live session %s closed on device %d", session, device_id)


# --- HLS ---

# A player asks for a playlist part every 200 ms or so. The access check opens a
# database session, so its result is kept this long per user and device.
ACCESS_TTL_SECONDS = 30.0
_access: dict[tuple[int, str, int], tuple[float, str]] = {}


def clear_access_cache() -> None:
    _access.clear()


async def _streaming_url(request: Request, device_id: int) -> str:
    """The device's live_url, if this user may see it and it streams.

    404 without access, 503 when not streaming. Only a success is cached, so a
    feeder that starts streaming is seen at once.
    """
    key = (request.state.user_id, request.state.role, device_id)
    now = time.monotonic()
    hit = _access.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    device = await _visible_device(request, device_id)
    if not live_available(device):
        raise _not_streaming()
    # Drop expired entries, so the table holds only recent viewers.
    for k in [k for k, (expires, _) in _access.items() if expires <= now]:
        del _access[k]
    _access[key] = (now + ACCESS_TTL_SECONDS, device.live_url)
    return device.live_url


@dataclass
class _HlsFileOperation(Operation):
    """Documents the bytes MediaMTX sends. The handler returns them as a Stream."""

    def __post_init__(self) -> None:
        binary = Schema(type="string", format="binary")
        self.responses = {
            **(self.responses or {}),
            "200": OpenAPIResponse(
                description="A playlist, an init segment, a segment or a part",
                content={
                    "application/vnd.apple.mpegurl": OpenAPIMediaType(schema=Schema(type="string")),
                    "video/mp4": OpenAPIMediaType(schema=binary),
                },
            ),
            "302": OpenAPIResponse(
                description="MediaMTX's cookie check. Follow Location without a cookie.",
                headers={"Location": OpenAPIHeader(schema=Schema(type="string"))},
            ),
        }


class LiveHlsController(Controller):
    path = "/devices/{device_id:int}/live/hls"
    tags = ["devices"]

    @get("/{name:path}", guards=[user_guard], security=USER_JWT, operation_class=_HlsFileOperation)
    async def hls_file(
        self, device_id: FromPath[int], name: FromPath[str], request: Request
    ) -> Stream | Response[bytes]:
        """Relay one HLS file from the feeder: a playlist, an init segment, a segment or a part.

        Start at `index.m3u8`. The query string goes to MediaMTX unchanged, so
        LL-HLS blocking reloads (`_HLS_msn`, `_HLS_part`) work. 503 means the
        feeder is not streaming.
        """
        name = name.lstrip("/")
        if not hls.HLS_FILE.match(name):
            raise NotFoundException()
        live_url = await _streaming_url(request, device_id)
        query = request.scope.get("query_string", b"").decode("latin-1")
        try:
            upstream = await hls.open_file(live_url, name, query)
        except whep.NotStreaming:
            raise _not_streaming()
        except hls.Moved as moved:
            # MediaMTX's cookie check. See backend/live/hls.py.
            return Response(content=b"", status_code=302,
                            headers={"Location": moved.location, "Cache-Control": "no-store"})
        except whep.Refused as exc:
            logger.warning("live HLS %s on device %d: %s", name, device_id, exc)
            if exc.status == 400:
                raise HTTPException(status_code=400, detail="feeder rejected the request")
            raise HTTPException(status_code=502, detail="feeder refused the request")
        headers = {"Cache-Control": "no-store"} if hls.is_playlist(name) else {}
        return Stream(upstream.body(), media_type=upstream.content_type, headers=headers)
