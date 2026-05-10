import asyncio
import csv
import logging
from pathlib import Path
from typing import NamedTuple

import numpy as np

from .base import ClassificationResult, ClassifierBase

logger = logging.getLogger(__name__)

_INPUT_SIZE = 224


class _Taxon(NamedTuple):
    common_name: str
    genus: str
    species: str


def _load_taxonomy(path: str) -> list[_Taxon]:
    """Parse taxonomy.csv into an ordered list indexed by model output position.

    Expected columns (case-insensitive): common_name, genus, species.
    Rows must appear in the same order as the model's output indices.
    """
    taxa: list[_Taxon] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Normalise header names to lowercase
        for row in reader:
            row = {k.lower(): v for k, v in row.items()}
            taxa.append(
                _Taxon(
                    common_name=row.get("common_name") or row.get("name") or "Unknown",
                    genus=row.get("genus") or "",
                    species=row.get("species") or "",
                )
            )
    return taxa


def _preprocess(image_path: Path, as_uint8: bool) -> np.ndarray:
    from PIL import Image

    img = Image.open(image_path).convert("RGB").resize((_INPUT_SIZE, _INPUT_SIZE))
    arr = np.array(img, dtype=np.uint8 if as_uint8 else np.float32)
    if not as_uint8:
        arr = arr / 255.0
    return np.expand_dims(arr, axis=0)


class TFLiteClassifier(ClassifierBase):
    """Tier 1 — on-device INatVision TFLite inference."""

    def __init__(self, model_path: str, taxonomy_path: str):
        self._model_path = model_path
        self._taxonomy_path = taxonomy_path
        self._interp = None
        self._taxa: list[_Taxon] = []
        self._input_uint8 = False

    def load(self) -> bool:
        """Load model + taxonomy. Returns False if any asset is missing or the runtime is absent."""
        if not Path(self._model_path).exists():
            logger.error("TFLite model not found: %s", self._model_path)
            return False
        if not Path(self._taxonomy_path).exists():
            logger.error("Taxonomy CSV not found: %s", self._taxonomy_path)
            return False

        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import tensorflow.lite as tflite  # type: ignore[no-redef]
            except ImportError:
                logger.error("Neither tflite_runtime nor tensorflow is installed")
                return False

        self._interp = tflite.Interpreter(model_path=self._model_path)
        self._interp.allocate_tensors()
        self._input_uint8 = self._interp.get_input_details()[0]["dtype"] == np.uint8
        self._taxa = _load_taxonomy(self._taxonomy_path)
        logger.info("TFLite model loaded (%d taxa)", len(self._taxa))
        return True

    @property
    def tier_name(self) -> str:
        return "local"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        if self._interp is None:
            return None
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._infer, image_path
            )
        except Exception:
            logger.exception("TFLite inference failed for %s", image_path)
            return None

    def _infer(self, image_path: Path) -> ClassificationResult | None:
        input_data = _preprocess(image_path, self._input_uint8)
        inp = self._interp.get_input_details()[0]
        out = self._interp.get_output_details()[0]

        self._interp.set_tensor(inp["index"], input_data)
        self._interp.invoke()
        scores = self._interp.get_tensor(out["index"])[0]

        top = int(np.argmax(scores))
        confidence = float(scores[top])

        if top >= len(self._taxa):
            logger.warning("Model output index %d exceeds taxonomy length %d", top, len(self._taxa))
            return None

        taxon = self._taxa[top]
        sci = f"{taxon.genus} {taxon.species}".strip() or "Unknown"
        return ClassificationResult(
            common_name=taxon.common_name,
            scientific_name=sci,
            confidence=confidence,
            tier_used="local",
        )
