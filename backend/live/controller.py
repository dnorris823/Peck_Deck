"""Relay WebRTC signaling between the web app and a feeder's MediaMTX.

The web app runs on HTTPS, and a browser on an HTTPS page cannot POST to
``http://<pi>:8889``. Sending the offer here keeps it same-origin and keeps the
JWT and device access rules in force. See docs/live-video.md.

Neither route takes the ``db`` dependency. It holds a session and a transaction
for the whole request, and the first offer can wait 15 seconds for MediaMTX to
start the encoder. A short session does the lookup and closes before the
upstream call.
"""
import logging
from dataclasses import dataclass

from litestar import Controller, Request, Response, delete, post
from litestar.exceptions import HTTPException, NotFoundException
from litestar.datastructures import ResponseHeader
from litestar.openapi.spec import OpenAPIMediaType, Operation, RequestBody, Schema
from litestar.params import FromPath

from ..auth.guards import user_guard
from ..database.connection import get_session_factory
from ..devices.controller import live_available
from ..devices.operations import get_device
from ..sightings.operations import user_can_access_device
from . import whep

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

    @delete("/{session:str}", guards=[user_guard], status_code=204)
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
