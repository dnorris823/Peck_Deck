"""Developer-only conveniences. Off unless ``DEV_TOOLS=1``.

``POST /dev/sighting`` fabricates one sighting of a random catalogued species,
on a random station the caller can see. It exists because the web app fetches
its dataset **once, on mount** — so a running feeder (or
``python -m backend.simulator``) produces nothing visible until the page is
reloaded, and "is this thing on?" is otherwise a two-terminal question.

It is not a second upload path. The row is written by
:func:`~backend.sightings.operations.create_sighting` and followed by
:func:`~backend.sightings.aftercare.schedule_aftercare` — the same two calls
``POST /sightings`` makes — so a fabricated visit lands in the database, the
dashboard aggregates and the notification fan-out exactly like a real one. What
it skips is the wire: no multipart, no device token. The Pi contract is pinned
by the simulator and the contract tests, and this must not become a third
implementation of it.

The route is registered unconditionally but 404s when ``DEV_TOOLS`` is off, so
a normal instance is indistinguishable from one that never had the route. It is
kept out of the OpenAPI document (``include_in_schema=False``) because it is not
part of the Pi/frontend contract.
"""
import json
import logging
import random
from datetime import datetime, timezone

from litestar import Controller, Request, post
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from ..config import settings
from ..database.models import Sighting, Species
from ..sightings.aftercare import schedule_aftercare
from ..sightings.operations import _accessible_device_ids, create_sighting
from ..simulator import pick_tier

logger = logging.getLogger("peckdeck.dev")


async def _random_species(db: AsyncSession) -> Species | None:
    """A random row from the species catalogue.

    Drawn from the database rather than ``machine_learning/feeder_species.csv``
    on purpose: the CSV is not in the API container image (the Dockerfile copies
    only ``backend/``), and whatever this instance has actually recorded is a
    better source of plausible birds than a file it may not have.
    """
    result = await db.execute(select(Species).order_by(func.random()).limit(1))
    return result.scalar_one_or_none()


async def _image_for(db: AsyncSession, species: Species) -> bytes | None:
    """Bytes for the fabricated capture, best-effort.

    Prefers an image this species already has: it is the plate the simulator
    drew for it, so the new sighting looks like its neighbours, and it needs no
    dependency the API container lacks. Falls back to drawing one, which only
    works where Pillow is installed (it is a *dev* dependency — see
    ``backend/demo_images.py``). Failing both, ``None`` is fine: the web app
    renders its SVG species plate for a sighting with no photo.
    """
    existing = await db.execute(
        select(Sighting.image_data)
        .where(Sighting.species_id == species.id, Sighting.image_data.is_not(None))
        .order_by(Sighting.id.desc())
        .limit(1)
    )
    row = existing.scalar_one_or_none()
    if row:
        return row

    try:
        from ..demo_images import plate_for

        palette = json.loads(species.palette) if species.palette else []
        return plate_for(palette or ["#7a8a8c", "#2a3032", "#ece4d2"])
    except Exception:
        logger.debug("no placeholder image available for %s", species.common_name)
        return None


class DevController(Controller):
    path = "/dev"

    @post("/sighting", guards=[user_guard], status_code=201, include_in_schema=False)
    async def simulate_sighting(
        self, request: Request, db: NamedDependency[AsyncSession]
    ) -> dict:
        if not settings.DEV_TOOLS:
            # Deliberately a 404 rather than a 403: a disabled dev tool should
            # look like a route that does not exist.
            raise NotFoundException()

        device_ids = await _accessible_device_ids(db, request.state.user_id)
        if not device_ids:
            raise HTTPException(
                status_code=409,
                detail="No stations to simulate a visit on — register a device first.",
            )

        species = await _random_species(db)
        if species is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No species catalogued yet, so there is nothing to simulate. "
                    "Seed the database or let a feeder record one real visit first."
                ),
            )

        tier, confidence = pick_tier(random.Random())
        device_id = random.choice(device_ids)
        sighting = await create_sighting(
            db,
            device_id=device_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            common_name=species.common_name,
            scientific_name=f"{species.genus} {species.species_name}".strip(),
            confidence_score=confidence,
            classification_tier_used=tier,
            image_data=await _image_for(db, species),
            delayed=False,
        )

        logger.info(
            "dev-tools: fabricated sighting %d — %s on device %d (tier=%s, %.2f)",
            sighting.id, species.common_name, device_id, tier, confidence,
        )

        await schedule_aftercare(db, sighting)

        return {
            "id": sighting.id,
            "common_name": species.common_name,
            "scientific_name": f"{species.genus} {species.species_name}".strip(),
            "device_id": device_id,
            "classification_tier_used": tier,
            "confidence_score": confidence,
            "datetime": sighting.datetime.isoformat(),
            "has_image": sighting.image_data is not None,
        }
