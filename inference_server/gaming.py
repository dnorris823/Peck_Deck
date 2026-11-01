"""Free the GPU while a game runs.

The ViT-L model holds VRAM the whole time the server runs. ``Tier2Model``
owns the loaded classifier and can drop it and load it again. The server
reports one state:

- ``ready``: the model is loaded and ``POST /classify`` answers.
- ``loading``: the model is loading. ``POST /classify`` returns 503.
- ``paused_manual``: the owner turned Tier 2 off. Only the owner turns it on.
- ``paused_game``: ``GameWatcher`` saw a game. It turns Tier 2 on again when
  the GPU goes quiet.
- ``failed``: the model did not load. A resume tries again.

While Tier 2 is not ``ready``, the Pi falls back to Tier 1 and the backend's
re-check holds its pending sightings.

``GameWatcher`` reads GPU use through NVML. On Windows, NVML lists the desktop
compositor and every browser as holding a graphics context, so a graphics
context cannot tell a game from the desktop. The watcher goes by sustained GPU
use alone. Readings taken just after this server classified an image are
skipped, so a re-check backlog never pauses Tier 2 by its own load.

A pause is not saved. A restarted server loads the model.
"""
import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

READY = "ready"
LOADING = "loading"
PAUSED_MANUAL = "paused_manual"
PAUSED_GAME = "paused_game"
FAILED = "failed"

# A reading this soon after a classify call holds some of our own load. NVML
# averages use over at most the last second.
OWN_LOAD_SECONDS = 2.0


class Classifier(Protocol):
    def classify(self, image_bytes: bytes): ...

    def unload(self) -> None: ...


class Tier2Model:
    """The loaded classifier, and whether Tier 2 may use it.

    Only one load runs at a time. A pause during a load frees the model as soon
    as the load ends. Call every method from the event loop.
    """

    def __init__(self, load: Callable[[], Classifier | None]):
        self._load_fn = load
        self._classifier: Classifier | None = None
        self._state = LOADING
        # The state the owner or the watcher asked for last.
        self._want = READY
        self._load_task: asyncio.Task | None = None
        # Set by the owner's resume. The watcher does not pause for the game
        # that is running now, only for the next one.
        self.hold_game_pause = False
        # time.monotonic() when the last classify call ended.
        self.last_busy = float("-inf")

    @property
    def state(self) -> str:
        return self._state

    @property
    def classifier(self) -> Classifier | None:
        """The classifier, or None unless the state is ``ready``."""
        return self._classifier if self._state == READY else None

    def mark_busy(self) -> None:
        self.last_busy = time.monotonic()

    def pause(self, state: str) -> None:
        """Drop the model now. ``state`` is ``paused_manual`` or ``paused_game``."""
        if state not in (PAUSED_MANUAL, PAUSED_GAME):
            raise ValueError(f"not a paused state: {state}")
        if state == PAUSED_MANUAL:
            self.hold_game_pause = False
        self._want = state
        self._state = state
        clf, self._classifier = self._classifier, None
        if clf is not None:
            clf.unload()
            logger.info("Tier 2 %s. Model unloaded", state)

    def resume(self, *, manual: bool = False) -> None:
        """Load the model in the background. A no-op when it is ready.

        ``manual`` is the owner's switch. It also holds off the game pause
        until the GPU next goes quiet, so a running game does not pause Tier 2
        again 30 s later.
        """
        if manual:
            self.hold_game_pause = True
        self._want = READY
        if self._state == READY:
            return
        self._state = LOADING
        if self._load_task is None or self._load_task.done():
            self._load_task = asyncio.create_task(self._load())

    async def _load(self) -> None:
        logger.info("Tier 2 loading the model")
        try:
            clf = await asyncio.to_thread(self._load_fn)
        except Exception:
            logger.exception("Tier 2 model load raised")
            clf = None
        if self._want != READY:
            # Paused while it loaded. The pause already set the state.
            if clf is not None:
                clf.unload()
            logger.info("Tier 2 paused during the load. Model unloaded")
            return
        if clf is None:
            self._state = FAILED
            logger.warning("Tier 2 model did not load. /classify returns 503")
            return
        self._classifier = clf
        self._state = READY
        logger.info("Tier 2 ready")

    async def wait_loaded(self) -> None:
        """Wait for a load in flight. The server waits for the first one."""
        if self._load_task is not None:
            await asyncio.gather(self._load_task, return_exceptions=True)


class GameWatcher:
    """Pause Tier 2 while the GPU stays busy, and resume when it goes quiet.

    Each ``tick`` takes one GPU use reading, in percent. Tier 2 pauses when
    the mean over the last ``pause_after`` seconds reaches ``pause_percent``.
    It resumes when the mean over the last ``resume_after`` seconds is at or
    below ``resume_percent``. A mean needs readings that span the whole period,
    at least half of the ones expected. Skipped readings count as missing.
    """

    def __init__(
        self,
        model: Tier2Model,
        read_use: Callable[[], float],
        *,
        pause_percent: float,
        pause_after: float,
        resume_percent: float,
        resume_after: float,
        sample_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not 0 <= resume_percent < pause_percent <= 100:
            raise ValueError(
                "GAME_RESUME_PERCENT must be below GAME_PAUSE_PERCENT, both 0 to 100"
            )
        if pause_after <= 0 or resume_after <= 0 or sample_seconds <= 0:
            raise ValueError("GAME_* periods must be more than 0 seconds")
        self._model = model
        self._read_use = read_use
        self._pause_percent = pause_percent
        self._pause_after = pause_after
        self._resume_percent = resume_percent
        self._resume_after = resume_after
        self._sample = sample_seconds
        self._clock = clock
        self._readings: deque[tuple[float, float]] = deque()

    def _mean_over(self, now: float, seconds: float) -> float | None:
        """Mean use over the last ``seconds``, or None without enough readings."""
        if not self._readings or now - self._readings[0][0] < seconds - self._sample:
            return None
        recent = [use for t, use in self._readings if now - t <= seconds]
        if len(recent) < max(1, seconds / self._sample / 2):
            return None
        return sum(recent) / len(recent)

    def tick(self) -> None:
        now = self._clock()
        if now - self._model.last_busy >= OWN_LOAD_SECONDS:
            self._readings.append((now, float(self._read_use())))
        keep = max(self._pause_after, self._resume_after) + self._sample
        while self._readings and now - self._readings[0][0] > keep:
            self._readings.popleft()

        busy = self._mean_over(now, self._pause_after)
        model = self._model
        if model.hold_game_pause and busy is not None and busy < self._pause_percent:
            model.hold_game_pause = False
            logger.info("GPU use fell. A game will pause Tier 2 again")

        state = model.state
        if (
            state in (READY, LOADING)
            and not model.hold_game_pause
            and busy is not None
            and busy >= self._pause_percent
        ):
            logger.info(
                "GPU use averaged %.0f%% over %.0f s. Pausing Tier 2 for a game",
                busy, self._pause_after,
            )
            model.pause(PAUSED_GAME)
        elif state == PAUSED_GAME:
            quiet = self._mean_over(now, self._resume_after)
            if quiet is not None and quiet <= self._resume_percent:
                logger.info(
                    "GPU use averaged %.0f%% over %.0f s. Resuming Tier 2",
                    quiet, self._resume_after,
                )
                model.resume()

    async def run(self) -> None:
        failing = False
        while True:
            try:
                self.tick()
                failing = False
            except Exception:
                # A failed reading must not end the loop. Log the first only.
                if not failing:
                    logger.exception("Reading GPU use failed")
                failing = True
            await asyncio.sleep(self._sample)


def nvml_reader(device: str) -> tuple[Callable[[], float], Callable[[], None]] | None:
    """A GPU use reader for the device, and its shutdown, or None without NVML.

    ``device`` is the server's ``DEVICE``, such as ``cuda`` or ``cuda:1``. A
    CPU device has no GPU to free.
    """
    if not device.startswith("cuda"):
        return None
    index = int(device.partition(":")[2] or 0)
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
    except Exception as exc:
        logger.warning("NVML not available (%s). The game pause is off", exc)
        return None

    def read() -> float:
        return float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)

    return read, pynvml.nvmlShutdown
