import logging
from datetime import datetime
from typing import Annotated

from litestar import Controller, Request, delete, get, post
from litestar.background_tasks import BackgroundTask
from litestar.datastructures import UploadFile
from litestar.di import NamedDependency
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import device_guard, user_guard
from ..devices.operations import mark_device_seen
from ..events.hub import SightingDeleted, sighting_hub
from . import export as export_ops
from .aftercare import schedule_aftercare
from .operations import (
    create_sighting,
    delete_sighting,
    get_sighting,
    get_sighting_device,
    list_sightings,
)
from .schemas import SightingResponse, sighting_response

logger = logging.getLogger("peckdeck.sightings")


_to_response = sighting_response

IMAGE_CACHE_CONTROL = "private, max-age=31536000, immutable"


async def _announce_deleted(event: SightingDeleted) -> None:
    # BackgroundTask awaits its function, and publish() is sync.
    sighting_hub.publish(event)


from dataclasses import dataclass, field


@dataclass
class SightingUploadForm:
    image: UploadFile
    timestamp: str
    common_name: str
    scientific_name: str
    confidence_score: str
    classification_tier_used: str
    delayed: str = "false"


class SightingController(Controller):
    path = "/sightings"

    @get("/", guards=[user_guard])
    async def list_sightings(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        device_id: FromQuery[int | None] = None,
        species_id: FromQuery[int | None] = None,
        from_date: FromQuery[str | None] = None,
        to_date: FromQuery[str | None] = None,
        limit: FromQuery[int] = 50,
        offset: FromQuery[int] = 0,
    ) -> list[SightingResponse]:
        try:
            from_dt = datetime.fromisoformat(from_date) if from_date else None
            to_dt = datetime.fromisoformat(to_date) if to_date else None
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="from_date/to_date must be ISO-8601 (e.g. 2026-07-19 or 2026-07-19T10:00:00)",
            )
        rows = await list_sightings(
            db,
            request.state.user_id,
            device_id=device_id,
            species_id=species_id,
            from_date=from_dt,
            to_date=to_dt,
            limit=min(limit, 100),
            offset=offset,
        )
        return [_to_response(s, has_image=has_image) for s, has_image in rows]

    @get("/export", guards=[user_guard])
    async def export(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        fmt: FromQuery[str] = "csv",
        device_id: FromQuery[int | None] = None,
        species_id: FromQuery[int | None] = None,
        from_date: FromQuery[str | None] = None,
        to_date: FromQuery[str | None] = None,
    ) -> Response:
        """Download sighting history as CSV or JSON, scoped to this user.

        Returned as an attachment so a browser saves it rather than rendering.
        Image bytes are excluded — each row carries `image_url` instead, since
        inlining them would make the file enormous.
        """
        fmt = fmt.lower()
        if fmt not in {"csv", "json"}:
            raise HTTPException(status_code=400, detail="fmt must be 'csv' or 'json'")

        try:
            from_dt = datetime.fromisoformat(from_date) if from_date else None
            to_dt = datetime.fromisoformat(to_date) if to_date else None
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="from_date/to_date must be ISO-8601 (e.g. 2026-07-19 or 2026-07-19T10:00:00)",
            )

        rows = await export_ops.collect_rows(
            db,
            request.state.user_id,
            device_id=device_id,
            species_id=species_id,
            from_date=from_dt,
            to_date=to_dt,
        )

        name = export_ops.filename(fmt)
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}

        if fmt == "csv":
            return Response(
                content=export_ops.to_csv(rows),
                media_type="text/csv",
                headers=headers,
            )
        return Response(content=rows, media_type="application/json", headers=headers)

    @post("/", guards=[device_guard], status_code=201)
    async def create(
        self,
        data: Annotated[SightingUploadForm, Body(media_type=RequestEncodingType.MULTI_PART)],
        request: Request,
        db: NamedDependency[AsyncSession],
    ) -> SightingResponse:
        image_bytes = await data.image.read()
        sighting = await create_sighting(
            db,
            device_id=request.state.device_id,
            timestamp=data.timestamp,
            common_name=data.common_name,
            scientific_name=data.scientific_name,
            confidence_score=float(data.confidence_score),
            classification_tier_used=data.classification_tier_used,
            image_data=image_bytes if image_bytes else None,
            delayed=data.delayed.lower() == "true",
        )
        # Now, not the capture time: a delayed upload from the offline queue
        # still proves the station is up.
        await mark_device_seen(db, request.state.device_id)

        logger.info(
            "sighting %d created on device %d (tier=%s, confidence=%.2f, delayed=%s)",
            sighting.id, sighting.device_id, sighting.classification_tier_used,
            sighting.confidence_score, sighting.delayed,
        )

        # Notifications, species enrichment and the live stream.
        await schedule_aftercare(db, sighting)

        return _to_response(sighting)

    @get("/{sighting_id:int}", guards=[user_guard])
    async def get_one(self, sighting_id: FromPath[int], db: NamedDependency[AsyncSession]) -> SightingResponse:
        sighting = await get_sighting(db, sighting_id)
        if sighting is None:
            raise NotFoundException()
        return _to_response(sighting)

    @get("/{sighting_id:int}/image", guards=[user_guard])
    async def get_image(self, sighting_id: FromPath[int], db: NamedDependency[AsyncSession]) -> Response[bytes]:
        sighting = await get_sighting(db, sighting_id)
        if sighting is None or sighting.image_data is None:
            raise NotFoundException()
        return Response(
            content=sighting.image_data,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="sighting_{sighting_id}.jpg"',
                # A sighting's image never changes after upload, so the browser
                # may keep it for a year. private keeps shared caches from
                # storing a response that needed a JWT.
                "Cache-Control": IMAGE_CACHE_CONTROL,
            },
        )

    @delete("/{sighting_id:int}", guards=[user_guard], status_code=204)
    async def delete_one(
        self, sighting_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> Response[None]:
        """Remove a sighting and its image. Device owner or owner role only."""
        target = await get_sighting_device(db, sighting_id)
        if target is None:
            raise NotFoundException()
        device_id, owner_id = target
        if owner_id != request.state.user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")

        await delete_sighting(db, sighting_id)
        logger.info(
            "sighting %d deleted from device %d by user %d",
            sighting_id, device_id, request.state.user_id,
        )

        # Published from a background task, which Litestar runs after the
        # response is sent. The `db` session commits before the send, so open
        # tabs hear of the delete only once it has landed. Their aggregate
        # refetch then cannot still count the row, and a failed commit sends
        # an error response and publishes nothing.
        return Response(
            content=None,
            status_code=204,
            background=BackgroundTask(
                _announce_deleted,
                SightingDeleted(sighting_id=sighting_id, device_id=device_id),
            ),
        )
