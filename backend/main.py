from litestar import Litestar, get, post
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.response import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database.connection import create_tables, dispose_db, init_db, provide_db
from .devices.controller import DeviceController
from .sightings.controller import SightingController
from .species.controller import SpeciesController
from .stats.controller import StatsController
from .users.controller import UserController, login


@get("/health", sync_to_thread=False)
def health() -> dict:
    return {"status": "ok"}


@post("/classify")
async def classify_stub() -> Response:
    raise HTTPException(
        status_code=501,
        detail="GPU inference server not yet available (Milestone 3)",
    )


async def on_startup(app: Litestar) -> None:
    init_db(settings.DATABASE_URL)
    await create_tables()


async def on_shutdown(app: Litestar) -> None:
    await dispose_db()


app = Litestar(
    route_handlers=[
        health,
        login,
        classify_stub,
        UserController,
        DeviceController,
        SpeciesController,
        SightingController,
        StatsController,
    ],
    dependencies={"db": Provide(provide_db)},
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
)
