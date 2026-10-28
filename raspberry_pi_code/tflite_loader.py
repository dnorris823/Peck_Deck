"""Find a TFLite runtime. Tier 1 and the camera trigger's bird detector share it."""

import logging
from types import ModuleType

logger = logging.getLogger(__name__)


def import_tflite() -> ModuleType | None:
    """Return the first TFLite interpreter module that imports, or None.

    Three names for the same runtime. `tflite_runtime` is what the Pi has.
    `ai_edge_litert` is its official successor and the only one of the three
    with a Windows wheel, which lets the accuracy harness
    (scripts/validate_tiers.py) run Tier 1 off the Pi. `tensorflow.lite` is the
    heavyweight fallback. All three expose `Interpreter` the same way.
    """
    try:
        import tflite_runtime.interpreter as tflite

        return tflite
    except ImportError:
        pass
    try:
        import ai_edge_litert.interpreter as tflite  # type: ignore[no-redef]

        return tflite
    except ImportError:
        pass
    try:
        import tensorflow.lite as tflite  # type: ignore[no-redef]

        return tflite
    except ImportError:
        pass
    logger.error(
        "No TFLite runtime found. Install one of tflite-runtime, ai-edge-litert, "
        "or tensorflow"
    )
    return None
