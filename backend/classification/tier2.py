"""Tier 2's pause switch, relayed to the inference server.

The inference server owns the state. It pauses itself while a game runs, and
the owner can pause it from the web app. The backend stores nothing. It asks
the server each time, so the switch always shows what the server reports.
See inference_server/gaming.py.

The relay sends ``INFERENCE_CONTROL_TOKEN`` as a Bearer token. The server
refuses ``/pause`` and ``/resume`` without it, and refuses both when it has no
token of its own. A refusal reaches the owner as a 502 with the server's
reason, never a 401 or 403, which the web app reads as "signed out" and
"viewer".
"""
from dataclasses import dataclass

from litestar import Controller, get, put
from litestar.exceptions import HTTPException

from ..auth.guards import USER_JWT, owner_guard, user_guard
from ..config import settings
from ..sightings.recheck import InferenceClient, SwitchRefused

# The backend's own state, for a server that does not answer.
OFFLINE = "offline"

NO_API_TOKEN = "INFERENCE_CONTROL_TOKEN is not set on the API, so the switch is off."
NO_SERVER_TOKEN = "INFERENCE_CONTROL_TOKEN is not set on the GPU server, so the switch is off."


@dataclass
class Tier2Status:
    # ready, loading, paused_manual, paused_game or failed, from the server.
    # offline when the server does not answer.
    state: str
    # Whether the server pauses itself while a game runs. False without NVML.
    game_pause: bool
    # Why the owner's switch cannot work, or None when it should. A token that
    # is set on both sides but does not match shows only when the switch is used.
    switch_off: str | None = None


@dataclass
class Tier2Switch:
    # True unloads the model. False loads it, and during a game holds off the
    # game pause until the game ends.
    paused: bool


def _client() -> InferenceClient:
    return InferenceClient(settings.INFERENCE_SERVER_URL)


def _status(body: dict | None) -> Tier2Status:
    switch_off = NO_API_TOKEN if not settings.INFERENCE_CONTROL_TOKEN else None
    if body is None:
        return Tier2Status(state=OFFLINE, game_pause=False, switch_off=switch_off)
    # An older server sends no state, and no "control".
    state = body.get("state") or ("ready" if body.get("model_ready", True) else "loading")
    if switch_off is None and body.get("control") is False:
        switch_off = NO_SERVER_TOKEN
    return Tier2Status(
        state=str(state),
        game_pause=bool(body.get("game_pause", False)),
        switch_off=switch_off,
    )


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
        token = settings.INFERENCE_CONTROL_TOKEN
        if not token:
            raise HTTPException(status_code=503, detail=NO_API_TOKEN)
        try:
            body = await _client().set_paused(data.paused, token)
        except SwitchRefused as exc:
            raise HTTPException(
                status_code=502, detail=f"The GPU server refused the switch: {exc.detail}"
            ) from exc
        if body is None:
            raise HTTPException(status_code=503, detail="The GPU server is not answering")
        return _status(body)
