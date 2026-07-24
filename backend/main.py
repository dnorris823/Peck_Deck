import logging
from dataclasses import dataclass
from typing import Annotated

from litestar import Litestar, Response, get, post
from litestar.config.cors import CORSConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.spec import Components, SecurityScheme, Tag
from litestar.datastructures import UploadFile
from litestar.di import Provide
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException
from litestar.params import Body

from .auth.guards import device_guard
from .classification.claude import get_classifier
from .config import settings
from .database.connection import dispose_db, init_db, provide_db
from .demo import demo_readonly_middleware, maybe_seed_demo
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


@get("/meta", sync_to_thread=False)
def meta() -> dict:
    """Public, unauthenticated description of *this* instance.

    The frontend fetches this before the login screen so it can show the demo
    banner and pre-fill the demo credentials. Deliberately tiny and free of
    anything sensitive — it exposes only what an unauthenticated visitor needs
    in order to understand what they are looking at.
    """
    body: dict = {"demo_mode": settings.DEMO_MODE, "environment": settings.ENVIRONMENT}
    if settings.DEMO_MODE:
        # Only meaningful on a demo instance, where these are published
        # credentials for throwaway data — never emitted otherwise.
        from .seed import DEMO_PASSWORD, USERS

        body["demo_login"] = {"email": USERS[0]["email"], "password": DEMO_PASSWORD}
    return body


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


_API_DESCRIPTION = """
REST API for the Peck Deck smart bird feeder.

Two distinct kinds of caller, with separate credentials:

* **Users** (web app) — `POST /login` returns a JWT. Send it as
  `Authorization: Bearer <jwt>`. Roles are `owner` and `viewer`; owner-only
  routes are marked as such.
* **Devices** (Raspberry Pi feeders) — authenticate with their long-lived
  device token, also sent as `Authorization: Bearer <token>`. A device token is
  **not** accepted on user routes and vice versa.

Sighting images are stored in PostgreSQL as `bytea` and served from
`GET /sightings/{id}/image`, which requires a user JWT.

`GET /health` is liveness (never touches the database); `GET /ready` is
readiness (checks the database and migration state, 503 when not ready);
`GET /meta` describes the instance itself (notably whether it is running in
read-only demo mode).

With `DEMO_MODE=1` the instance seeds itself on first boot and rejects every
user-authenticated write with 403. Device-token routes (`POST /sightings`,
`POST /classify`, the heartbeat) and `POST /login` keep working, so the demo
stays live rather than frozen.
""".strip()

_OPENAPI_TAGS = [
    Tag(name="auth", description="Login and token issuance"),
    Tag(name="users", description="Accounts, roles, and per-user preferences"),
    Tag(name="devices", description="Feeder registration, status, and sharing"),
    Tag(name="sightings", description="Bird visits and their images"),
    Tag(name="species", description="Species reference data"),
    Tag(name="stats", description="Dashboard aggregates"),
    Tag(name="ops", description="Liveness, readiness, and classification relay"),
]

_INSECURE_JWT_DEFAULT = "change_this_in_production"


def _check_production_config() -> None:
    """Refuse to start a production process on insecure defaults.

    The JWT secret is what every user token is signed with — running production
    on the shipped default means anyone who has read the repo can forge an owner
    token. Failing loudly at boot is far better than discovering it later.
    """
    if settings.ENVIRONMENT.lower() != "production":
        return

    problems = []
    if settings.JWT_SECRET == _INSECURE_JWT_DEFAULT:
        problems.append("JWT_SECRET is still the shipped default")
    if len(settings.JWT_SECRET) < 32:
        problems.append("JWT_SECRET is shorter than 32 characters")
    if "*" in settings.CORS_ALLOW_ORIGINS:
        problems.append("CORS_ALLOW_ORIGINS must not contain '*' when credentials are allowed")

    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure configuration: "
            + "; ".join(problems)
        )


async def on_startup(app: Litestar) -> None:
    _check_production_config()
    # Schema is owned by Alembic, not by the app. `create_all()` used to run
    # here, but it only ever creates *missing* tables — it silently ignores
    # changes to existing ones, so any model change after the first deploy
    # would never actually reach the database. Migrations run before the app
    # starts (see backend/entrypoint.sh and scripts/migrate.sh).
    init_db(settings.DATABASE_URL)
    # No-ops unless DEMO_MODE is on and the database is empty.
    await maybe_seed_demo()


async def on_shutdown(app: Litestar) -> None:
    await dispose_db()


app = Litestar(
    route_handlers=[
        health,
        ready,
        meta,
        login,
        classify,
        UserController,
        DeviceController,
        SpeciesController,
        SightingController,
        StatsController,
    ],
    dependencies={"db": Provide(provide_db)},
    # Order matters: the request-context middleware is outermost, so a demo-mode
    # 403 still gets a request id and still shows up in the access log.
    middleware=[RequestContextMiddleware, demo_readonly_middleware],
    exception_handlers={
        HTTPException: http_exception_handler,
        Exception: unhandled_exception_handler,
    },
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
    cors_config=CORSConfig(
        allow_origins=[o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    ),
    # Cap request bodies so an oversized upload can't exhaust memory — sighting
    # images are buffered and stored as bytea.
    request_max_body_size=settings.MAX_UPLOAD_BYTES,
    # Served at /schema (Swagger UI, ReDoc, etc.) and /schema/openapi.json.
    # Deliberately public: it documents the Pi/frontend contract and exposes no
    # data, only the shape of the API.
    openapi_config=OpenAPIConfig(
        title="Peck Deck API",
        version="1.0.0",
        description=_API_DESCRIPTION,
        tags=_OPENAPI_TAGS,
        path="/schema",
        components=Components(
            security_schemes={
                "UserJWT": SecurityScheme(
                    type="http",
                    scheme="bearer",
                    bearer_format="JWT",
                    description="User JWT from POST /login.",
                ),
                "DeviceToken": SecurityScheme(
                    type="http",
                    scheme="bearer",
                    description=(
                        "Long-lived per-device token issued at device registration. "
                        "Used by the Pi for POST /sightings, POST /classify, and heartbeats."
                    ),
                ),
            },
        ),
    ),
)
