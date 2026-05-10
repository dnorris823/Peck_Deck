import logging
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .classifier import BirdClassifier
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_classifier: BirdClassifier | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _classifier
    clf = BirdClassifier(
        model_name=settings.MODEL_NAME,
        taxonomy_path=settings.TAXONOMY_PATH,
        image_size=settings.IMAGE_SIZE,
        weights_path=settings.MODEL_PATH,
        device=settings.DEVICE,
    )
    ok = clf.load()
    if ok:
        _classifier = clf
    else:
        logger.warning("Classifier not loaded — /classify will return 503 until fixed")
    yield
    _classifier = None


app = FastAPI(
    title="Peck Deck GPU Inference Server",
    description="Tier 2 bird-species classifier backed by a PyTorch model on RTX 5080",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_ready": _classifier is not None}


@app.post("/classify")
async def classify(image: Annotated[UploadFile, File(description="JPEG image of the bird")]) -> dict:
    """Accept a JPEG image and return the top-1 species prediction."""
    if _classifier is None:
        raise HTTPException(status_code=503, detail="Classifier not loaded")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image")

    result = _classifier.classify(image_bytes)
    if result is None:
        raise HTTPException(status_code=500, detail="Classification failed")

    return {
        "common_name": result.common_name,
        "scientific_name": result.scientific_name,
        "confidence": result.confidence,
    }


if __name__ == "__main__":
    uvicorn.run(
        "inference_server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )
