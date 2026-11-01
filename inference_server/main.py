import asyncio
import contextlib
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile

from .classifier import BirdClassifier
from .config import settings
from .gaming import (
    FAILED,
    LOADING,
    PAUSED_GAME,
    PAUSED_MANUAL,
    READY,
    GameWatcher,
    Tier2Model,
    nvml_reader,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_model: Tier2Model | None = None
# Whether the game watcher runs. Off without NVML, or with GAME_PAUSE_ENABLED=false.
_watching = False

# Why POST /classify returns 503, per state.
_UNAVAILABLE = {
    LOADING: "Tier 2 is loading the model",
    PAUSED_MANUAL: "Tier 2 is paused by the owner",
    PAUSED_GAME: "Tier 2 is paused while a game runs",
    FAILED: "Classifier not loaded",
}


def _load_classifier() -> BirdClassifier | None:
    clf = BirdClassifier(
        model_name=settings.MODEL_NAME,
        taxonomy_path=settings.TAXONOMY_PATH,
        image_size=settings.IMAGE_SIZE,
        weights_path=settings.MODEL_PATH,
        device=settings.DEVICE,
        animals_path=settings.ANIMALS_PATH,
    )
    return clf if clf.load() else None


def _start_watcher(model: Tier2Model) -> tuple[asyncio.Task | None, Callable[[], None] | None]:
    if not settings.GAME_PAUSE_ENABLED:
        logger.info("Game pause off (GAME_PAUSE_ENABLED is false)")
        return None, None
    nvml = nvml_reader(settings.DEVICE)
    if nvml is None:
        return None, None
    read, shutdown = nvml
    watcher = GameWatcher(
        model,
        read,
        pause_percent=settings.GAME_PAUSE_PERCENT,
        pause_after=settings.GAME_PAUSE_AFTER_SECONDS,
        resume_percent=settings.GAME_RESUME_PERCENT,
        resume_after=settings.GAME_RESUME_AFTER_SECONDS,
        sample_seconds=settings.GAME_SAMPLE_SECONDS,
    )
    logger.info(
        "Game pause on: pause at %.0f%% GPU use for %.0f s, resume at %.0f%% for %.0f s",
        settings.GAME_PAUSE_PERCENT, settings.GAME_PAUSE_AFTER_SECONDS,
        settings.GAME_RESUME_PERCENT, settings.GAME_RESUME_AFTER_SECONDS,
    )
    return asyncio.create_task(watcher.run()), shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _watching
    _model = Tier2Model(_load_classifier)
    # The first load ends before the server takes requests, as it always has.
    # Later loads, after a pause, run in the background.
    _model.resume()
    await _model.wait_loaded()
    task, shutdown = _start_watcher(_model)
    _watching = task is not None
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    if shutdown is not None:
        shutdown()
    _model = None
    _watching = False


app = FastAPI(
    title="Peck Deck GPU Inference Server",
    description="Tier 2 bird-species classifier backed by a PyTorch model on RTX 5080",
    version="1.0.0",
    lifespan=lifespan,
)


def _status() -> dict:
    state = _model.state if _model is not None else LOADING
    return {
        "status": "ok",
        "model_ready": state == READY,
        "state": state,
        "game_pause": _watching,
    }


@app.get("/health")
def health() -> dict:
    """``state`` is ready, loading, paused_manual, paused_game or failed."""
    return _status()


# async, so they run on the event loop with the model and its load task.
@app.post("/pause")
async def pause() -> dict:
    """Unload the model until ``POST /resume``. The game watcher never resumes it."""
    if _model is not None:
        _model.pause(PAUSED_MANUAL)
    return _status()


@app.post("/resume")
async def resume() -> dict:
    """Load the model. Returns at once, usually with state ``loading``.

    During a game this holds off the game pause until the GPU goes quiet.
    """
    if _model is not None:
        _model.resume(manual=True)
    return _status()


@app.post("/classify")
async def classify(image: Annotated[UploadFile, File(description="JPEG image of the bird")]) -> dict:
    """Accept a JPEG image. Return the top-1 bird and the best feeder animal.

    ``animal`` is the best row of ``feeder_animals.csv`` from the same softmax,
    or null. The Pi decides whether it beats the bird.
    """
    clf = _model.classifier if _model is not None else None
    if clf is None:
        state = _model.state if _model is not None else LOADING
        raise HTTPException(status_code=503, detail=_UNAVAILABLE.get(state, "Classifier not loaded"))

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image")

    try:
        result = clf.classify(image_bytes)
    finally:
        # The game watcher skips GPU readings that hold this call's load.
        _model.mark_busy()
    if result is None:
        raise HTTPException(status_code=500, detail="Classification failed")

    return {
        "common_name": result.common_name,
        "scientific_name": result.scientific_name,
        "confidence": result.confidence,
        "animal": asdict(result.animal) if result.animal is not None else None,
    }


if __name__ == "__main__":
    uvicorn.run(
        "inference_server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )
