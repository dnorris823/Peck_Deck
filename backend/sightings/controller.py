import asyncio
import logging
from datetime import datetime
from typing import Annotated

from litestar import Controller, Request, get, post
from litestar.datastructures import UploadFile
from litestar.di import NamedDependency
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import device_guard, user_guard
from ..notifications.service import notification_service
from ..notifications.wikipedia import update_species_wiki_url
from ..species.operations import get_species
from .operations import create_sighting, get_sighting, list_sightings
from .schemas import SightingResponse

logger = logging.getLogger("peckdeck.sightings")


def _to_response(s) -> SightingResponse:
    return SightingResponse(
        id=s.id,
        species_id=s.species_id,
        device_id=s.device_id,
        datetime=s.datetime.isoformat(),
        classification_tier_used=s.classification_tier_used,
        confidence_score=s.confidence_score,
        weather_conditions=s.weather_conditions,
        delayed=s.delayed,
        has_image=s.image_data is not None,
    )


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
        sightings = await list_sightings(
            db,
            request.state.user_id,
            device_id=device_id,
            species_id=species_id,
            from_date=from_dt,
            to_date=to_dt,
            limit=min(limit, 100),
            offset=offset,
        )
        return [_to_response(s) for s in sightings]

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

        logger.info(
            "sighting %d created on device %d (tier=%s, confidence=%.2f, delayed=%s)",
            sighting.id, sighting.device_id, sighting.classification_tier_used,
            sighting.confidence_score, sighting.delayed,
        )

        # Load species to check wiki_url while the session is still open
        species = await get_species(db, sighting.species_id)

        # Fire-and-forget background tasks — both open their own DB sessions,
        # so they run safely after the request transaction commits.
        asyncio.create_task(
            notification_service.dispatch(sighting.id, sighting.device_id)
        )
        if species is not None and species.wiki_url is None:
            sci = f"{species.genus} {species.species_name}".strip()
            asyncio.create_task(
                update_species_wiki_url(species.id, species.common_name, sci)
            )

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
            headers={"Content-Disposition": f'inline; filename="sighting_{sighting_id}.jpg"'},
        )
