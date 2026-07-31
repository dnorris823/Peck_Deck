"""Fire-and-forget work that follows a newly created sighting.

Extracted from :class:`~backend.sightings.controller.SightingController` so the
device upload path and the dev-tools path (``POST /dev/sighting``) schedule
exactly the same follow-up. A fabricated sighting that skipped notification
dispatch would be a poor stand-in for a real one — the whole point of the dev
button is to watch the real pipeline react.

Both tasks open their own database sessions, so they run safely after the
request transaction commits.
"""
import asyncio
import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.hub import SightingEvent, sighting_hub
from ..notifications.service import notification_service
from ..species.enrichment import enrich_species
from ..species.operations import get_species
from .schemas import sighting_response

logger = logging.getLogger("peckdeck.sightings")


async def schedule_aftercare(db: AsyncSession, sighting) -> None:
    """Dispatch notifications, enrich a sparse species, and stream the sighting.

    Must be awaited while ``db`` is still open: the species row is read here,
    before the tasks are spawned, because the session will be gone by the time
    they run.
    """
    species = await get_species(db, sighting.species_id)

    # Fan out to any open GET /events stream. Synchronous and swallowing its own
    # failures by construction (see backend/events/hub.py) — this runs on the
    # Pi's upload path, and a browser must never be able to slow it down or fail
    # it. Published before the transaction commits, which is safe here because
    # the payload travels with the event: a subscriber never reads the row back,
    # so it cannot race a commit that hasn't landed.
    sighting_hub.publish(
        SightingEvent(
            sighting_id=sighting.id,
            device_id=sighting.device_id,
            payload=asdict(sighting_response(sighting)),
        )
    )

    asyncio.create_task(
        notification_service.dispatch(sighting.id, sighting.device_id)
    )
    # Enrich once, on first sighting: anything still missing gets filled in
    # (wiki URL, description, family, order). Skipped when already complete so a
    # busy feeder doesn't hammer Wikipedia/GBIF on every visit.
    if species is not None and not (
        species.wiki_url and species.description and species.family
    ):
        sci = f"{species.genus} {species.species_name}".strip()
        asyncio.create_task(enrich_species(species.id, species.common_name, sci))
