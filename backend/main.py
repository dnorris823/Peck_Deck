import logging
from dataclasses import dataclass
from typing import Annotated

from litestar import Litestar, Response, get, post
from litestar.datastructures import UploadFile
from litestar.di import Provide
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException
from litestar.params import Body

from .auth.guards import device_guard
from .classification.claude import get_classifier
from .config import settings
from .database.connection import dispose_db, init_db, provide_db
from .devices.controller import DeviceController
from .errors import http_exception_handler, unhandled_exception_handler
from .observability import RequestContextMiddleware, configure_logging
from .readiness import check_readiness
from .sightings.controller import SightingController
from .species.controller import SpeciesController
from .stats.controller import StatsController
from .users.controller import UserController, login

configure_logging()
logger = logging.getLogger(__name__)


@get("/health", sync_to_thread=False)
def health() -> dict:
    """Liveness: is the process up? Deliberately cheap and dependency-free.

    Must not touch the database — a liveness probe that fails on a transient DB
    blip would have the orchestrator restart a perfectly healthy container.
    """
    return {"status": "ok"}


@get("/ready", status_code=200)
async def ready() -> Response[dict]:
    """Readiness: can this process serve traffic?

    Checks database connectivity and that the schema is migrated to a revision
    this build knows about. Returns 503 when not ready, so orchestration keeps
    the container out of the load balancer instead of restarting it.
    """
    ok, detail = await check_readiness()
    return Response(
        content={"status": "ready" if ok else "not_ready", **detail},
        status_code=200 if ok else 503,
    )


@dataclass
class ClassifyForm:
    image: UploadFile


@post("/classify", guards=[device_guard], status_code=200)
async def classify(
    data: Annotated[ClassifyForm, Body(media_type=RequestEncodingType.MULTI_PART)],
) -> dict:
    """Tier 3 — relay the Pi's image to Claude and return the species prediction."""
    image_bytes = await data.image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty or missing image")

    classifier = get_classifier()
    if classifier is None:
        raise HTTPException(
            status_code=503,
            detail="Cloud classification unavailable (ANTHROPIC_API_KEY not configured)",
        )

    try:
        result = await classifier.classify(image_bytes)
        logger.info(
            "tier3 classify -> %s (%.2f)",
            result.get("common_name"),
            result.get("confidence", 0.0),
        )
        return result
    except Exception:
        logger.exception("Cloud classification failed")
        raise HTTPException(status_code=502, detail="Cloud classification failed")


async def on_startup(app: Litestar) -> None:
    # Schema is owned by Alembic, not by the app. `create_all()` used to run
    # here, but it only ever creates *missing* tables — it silently ignores
    # changes to existing ones, so any model change after the first deploy
    # would never actually reach the database. Migrations run before the app
    # starts (see backend/entrypoint.sh and scripts/migrate.sh).
    init_db(settings.DATABASE_URL)


async def on_shutdown(app: Litestar) -> None:
    await dispose_db()


app = Litestar(
    route_handlers=[
        health,
        ready,
        login,
        classify,
        UserController,
        DeviceController,
        SpeciesController,
        SightingController,
        StatsController,
    ],
    dependencies={"db": Provide(provide_db)},
    middleware=[RequestContextMiddleware],
    exception_handlers={
        HTTPException: http_exception_handler,
        Exception: unhandled_exception_handler,
    },
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
)
