import asyncio
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from litestar import Controller, Request, delete, get, patch, post
from litestar.background_tasks import BackgroundTask
from litestar.datastructures import UploadFile
from litestar.di import NamedDependency
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import DEVICE_TOKEN, USER_JWT, device_guard, user_guard
from ..devices.operations import mark_device_seen
from ..events.hub import SightingDeleted, SightingsDeleted, SightingUpdated, sighting_hub
from ..species.operations import get_species
from . import export as export_ops
from .aftercare import schedule_aftercare
from .operations import (
    correct_species,
    create_sighting,
    delete_sighting,
    delete_sightings,
    get_image_bytes,
    get_sighting,
    get_sighting_device,
    get_sighting_devices,
    list_sightings,
    user_can_access_device,
)
from .schemas import (
    CorrectSpecies,
    DeletedCount,
    DeleteSightings,
    SightingResponse,
    parse_tier_trace,
    sighting_response,
)
from .thumbnails import make_thumbnail
from .weather import schedule_weather

logger = logging.getLogger("peckdeck.sightings")


_to_response = sighting_response

IMAGE_CACHE_CONTROL = "private, max-age=31536000, immutable"
# A thumbnail request answered with the full image, because the row has no
# thumbnail yet. A day, not a year, so the browser picks up the real thumbnail
# once the backfill has run.
FALLBACK_CACHE_CONTROL = "private, max-age=86400"


# A bulk delete takes at most this many ids. History holds 100 sightings, so
# the web app never comes near it. It bounds the IN list and the request body.
MAX_BULK_DELETE = 500


async def _announce(*events: SightingDeleted | SightingUpdated | SightingsDeleted) -> None:
    # BackgroundTask awaits its function, and publish() is sync.
    for event in events:
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
    # JSON list of TierAttempt objects. Older Pi builds leave it out.
    tier_trace: str | None = None


class SightingController(Controller):
    path = "/sightings"

    @get("/", guards=[user_guard], security=USER_JWT)
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

    @get("/export", guards=[user_guard], security=USER_JWT)
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

    @post("/", guards=[device_guard], security=DEVICE_TOKEN, status_code=201)
    async def create(
        self,
        data: Annotated[SightingUploadForm, Body(media_type=RequestEncodingType.MULTI_PART)],
        request: Request,
        db: NamedDependency[AsyncSession],
    ) -> Response[SightingResponse]:
        image_bytes = await data.image.read()
        # Off the event loop, since a decode takes tens of milliseconds. It
        # returns None rather than raise, so a bad image never fails the upload.
        thumbnail = await asyncio.to_thread(make_thumbnail, image_bytes) if image_bytes else None
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
            tier_trace=parse_tier_trace(data.tier_trace),
            thumbnail_data=thumbnail,
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

        # The weather lookup goes to Open-Meteo, so it starts after the
        # response, once the row has committed. A slow or failed lookup then
        # cannot delay or fail the upload.
        return Response(
            content=_to_response(sighting),
            status_code=201,
            background=BackgroundTask(schedule_weather, sighting.id),
        )

    @get("/{sighting_id:int}", guards=[user_guard], security=USER_JWT)
    async def get_one(self, sighting_id: FromPath[int], db: NamedDependency[AsyncSession]) -> SightingResponse:
        sighting = await get_sighting(db, sighting_id)
        if sighting is None:
            raise NotFoundException()
        return _to_response(sighting)

    @get("/{sighting_id:int}/image", guards=[user_guard], security=USER_JWT)
    async def get_image(
        self,
        sighting_id: FromPath[int],
        db: NamedDependency[AsyncSession],
        size: FromQuery[Literal["full", "thumb"]] = "full",
    ) -> Response[bytes]:
        """The capture as a JPEG. ``size=thumb`` returns about 400 px on the long
        side, or the full image if the sighting has no thumbnail."""
        found = await get_image_bytes(db, sighting_id, thumb=size == "thumb")
        if found is None:
            raise NotFoundException()
        content, is_thumb = found
        suffix = "_thumb" if is_thumb else ""
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="sighting_{sighting_id}{suffix}.jpg"',
                # A sighting's image never changes after upload, so the browser
                # may keep it for a year. private keeps shared caches from
                # storing a response that needed a JWT.
                "Cache-Control": (
                    FALLBACK_CACHE_CONTROL if size == "thumb" and not is_thumb else IMAGE_CACHE_CONTROL
                ),
            },
        )

    @patch("/{sighting_id:int}", guards=[user_guard], security=USER_JWT)
    async def correct(
        self,
        sighting_id: FromPath[int],
        data: CorrectSpecies,
        request: Request,
        db: NamedDependency[AsyncSession],
    ) -> Response[SightingResponse]:
        """Set the species a person says this is. Any user with access to the device.

        The Pi's tier, confidence and trace stay as uploaded, and
        `original_species_id` keeps the species the tier named.
        """
        target = await get_sighting_device(db, sighting_id)
        if target is None:
            raise NotFoundException()
        device_id, owner_id = target
        if not await user_can_access_device(
            db, request.state.user_id, request.state.role, device_id, owner_id
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        if await get_species(db, data.species_id) is None:
            raise HTTPException(status_code=400, detail=f"No species with id {data.species_id}")

        sighting, has_image = await correct_species(
            db, sighting_id, species_id=data.species_id, user_id=request.state.user_id
        )
        logger.info(
            "sighting %d on device %d set to species %d by user %d (tier %s said species %d)",
            sighting_id, device_id, sighting.species_id, request.state.user_id,
            sighting.classification_tier_used, sighting.original_species_id,
        )

        body = _to_response(sighting, has_image=has_image)
        # After the commit, for the reason given on delete_one below.
        return Response(
            content=body,
            background=BackgroundTask(
                _announce,
                SightingUpdated(
                    sighting_id=sighting_id, device_id=device_id, payload=asdict(body)
                ),
            ),
        )

    @post("/delete", guards=[user_guard], security=USER_JWT, status_code=200)
    async def delete_many(
        self, data: DeleteSightings, request: Request, db: NamedDependency[AsyncSession]
    ) -> Response[DeletedCount]:
        """Remove many sightings and their images. Device owner or owner role only.

        All or nothing: one id on a device the caller cannot manage refuses the
        whole request with 403. Ids that no longer exist are skipped, so a
        retry after a dropped response does not fail.
        """
        ids = sorted(set(data.ids))
        if not ids:
            raise HTTPException(status_code=400, detail="Send at least one id.")
        if len(ids) > MAX_BULK_DELETE:
            raise HTTPException(
                status_code=400, detail=f"Send at most {MAX_BULK_DELETE} ids per request."
            )
        targets = await get_sighting_devices(db, ids)
        user_id, role = request.state.user_id, request.state.role
        if any(owner_id != user_id and role != "owner" for _, _, owner_id in targets):
            raise HTTPException(status_code=403, detail="Forbidden")

        await delete_sightings(db, [sid for sid, _, _ in targets])
        per_device: dict[int, int] = {}
        for _, device_id, _ in targets:
            per_device[device_id] = per_device.get(device_id, 0) + 1
        logger.info(
            "%d sightings deleted from devices %s by user %d",
            len(targets), sorted(per_device), user_id,
        )

        # After the commit, for the reason given on delete_one below.
        return Response(
            content=DeletedCount(deleted=len(targets)),
            status_code=200,
            background=BackgroundTask(
                _announce,
                *(SightingsDeleted(device_id=d, count=n) for d, n in per_device.items()),
            ),
        )

    @delete("/{sighting_id:int}", guards=[user_guard], security=USER_JWT, status_code=204)
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
                _announce,
                SightingDeleted(sighting_id=sighting_id, device_id=device_id),
            ),
        )
