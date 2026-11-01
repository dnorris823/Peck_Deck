"""Tier 2's pause switch, relayed to the inference server.

The inference server owns the state. It pauses itself while a game runs, and
the owner can pause it from the web app. The backend stores nothing. It asks
the server each time, so the switch always shows what the server reports.
See inference_server/gaming.py.
"""
from dataclasses import dataclass

from litestar import Controller, get, put
from litestar.exceptions import HTTPException

from ..auth.guards import USER_JWT, owner_guard, user_guard
from ..config import settings
from ..sightings.recheck import InferenceClient

# The backend's own state, for a server that does not answer.
OFFLINE = "offline"


@dataclass
class Tier2Status:
    # ready, loading, paused_manual, paused_game or failed, from the server.
    # offline when the server does not answer.
    state: str
    # Whether the server pauses itself while a game runs. False without NVML.
    game_pause: bool


@dataclass
class Tier2Switch:
    # True unloads the model. False loads it, and during a game holds off the
    # game pause until the game ends.
    paused: bool


def _client() -> InferenceClient:
    return InferenceClient(settings.INFERENCE_SERVER_URL)


def _status(body: dict | None) -> Tier2Status:
    if body is None:
        return Tier2Status(state=OFFLINE, game_pause=False)
    # An older server sends no state.
    state = body.get("state") or ("ready" if body.get("model_ready", True) else "loading")
    return Tier2Status(state=str(state), game_pause=bool(body.get("game_pause", False)))


class Tier2Controller(Controller):
    path = "/tier2"
    tags = ["ops"]
    security = USER_JWT

    @get("/", guards=[user_guard])
    async def get_status(self) -> Tier2Status:
        """Tier 2's state, as the inference server reports it."""
        return _status(await _client().status())

    @put("/", guards=[owner_guard])
    async def set_paused(self, data: Tier2Switch) -> Tier2Status:
        """Pause or resume Tier 2. Owner only.

        A resume returns at once, usually with state ``loading``. Poll
        ``GET /tier2`` for ``ready``.
        """
        body = await _client().set_paused(data.paused)
        if body is None:
            raise HTTPException(status_code=503, detail="The GPU server is not answering")
        return _status(body)
