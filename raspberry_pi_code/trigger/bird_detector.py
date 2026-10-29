"""COCO object detector, used only to answer "is there a bird in this frame".

The model is EfficientDet-Lite0 from `scripts/fetch_models.py`. It runs on the
same TFLite runtime as Tier 1. It does not name the species. Tier 2 does that
after the capture.
"""

import logging
from pathlib import Path
from typing import NamedTuple

import numpy as np

from ..bird_crop import Box
from ..tflite_loader import import_tflite

logger = logging.getLogger(__name__)

# COCO "bird", as the model numbers it. The model's labelmap.txt starts at
# person = 0, so bird is line 16 and class 15. Check this if the model changes.
BIRD_CLASS_ID = 15


class Detection(NamedTuple):
    """The best bird in a frame.

    ``box`` is in fractions of the frame the detector was given. It is None
    when the model returned an empty box.
    """

    score: float
    box: Box | None


def _to_box(raw: np.ndarray) -> Box | None:
    """Convert the model's [ymin, xmin, ymax, xmax] to (x, y, width, height)."""
    ymin, xmin, ymax, xmax = np.clip(np.asarray(raw, dtype=float), 0.0, 1.0)
    if xmax <= xmin or ymax <= ymin:
        return None
    return (float(xmin), float(ymin), float(xmax - xmin), float(ymax - ymin))


class BirdDetector:
    """Wraps a TFLite detection model with the standard post-process outputs.

    The four outputs come in signature order: boxes [1, N, 4], classes [1, N],
    scores [1, N], count [1]. Both the EfficientDet-Lite and the SSD MobileNet
    COCO models follow it.
    """

    def __init__(self, model_path: str, score_threshold: float, num_threads: int = 4):
        if num_threads < 1:
            raise ValueError(f"DETECTOR_THREADS must be 1 or more, got {num_threads}")
        self._model_path = model_path
        self._threshold = score_threshold
        self._num_threads = num_threads
        self._interp = None
        self._input: dict | None = None
        self._boxes: dict | None = None
        self._classes: dict | None = None
        self._scores: dict | None = None
        self._count: dict | None = None

    def load(self) -> bool:
        """Load the model. Returns False if the file or the runtime is missing."""
        if not Path(self._model_path).exists():
            logger.error(
                "Bird detector model not found: %s. Run scripts/fetch_models.py",
                self._model_path,
            )
            return False
        tflite = import_tflite()
        if tflite is None:
            return False
        # TFLite runs on one thread unless told otherwise. All three runtimes in
        # tflite_loader accept num_threads.
        return self.attach(
            tflite.Interpreter(model_path=self._model_path, num_threads=self._num_threads)
        )

    def attach(self, interpreter) -> bool:
        """Use an interpreter that is already built. Tests pass a fake here."""
        interpreter.allocate_tensors()
        inp = interpreter.get_input_details()[0]
        outputs = interpreter.get_output_details()

        if len(outputs) != 4:
            logger.error(
                "Bird detector has %d outputs, expected 4 (boxes, classes, scores, "
                "count). Is it a detection model with post-processing?",
                len(outputs),
            )
            return False
        if inp["dtype"] != np.uint8:
            logger.error("Bird detector input is %s, expected uint8", inp["dtype"])
            return False

        self._interp = interpreter
        self._input = inp
        self._boxes, self._classes, self._scores, self._count = outputs
        logger.info(
            "Bird detector loaded (input %s, score threshold %.2f, %d threads)",
            tuple(inp["shape"]), self._threshold, self._num_threads,
        )
        return True

    @property
    def loaded(self) -> bool:
        return self._interp is not None

    def detect(self, rgb: np.ndarray) -> Detection | None:
        """Return the best bird at or above the threshold, else None.

        ``rgb`` is an (h, w, 3) uint8 frame of any size. Blocking: call it
        through ``asyncio.to_thread``.
        """
        if self._interp is None:
            return None

        from PIL import Image

        _, in_h, in_w, _ = self._input["shape"]
        # Squash to the input size without keeping the aspect ratio. The COCO
        # detectors were trained on resized inputs the same way.
        img = Image.fromarray(np.ascontiguousarray(rgb[..., :3])).resize(
            (int(in_w), int(in_h)), Image.BILINEAR
        )
        batch = np.expand_dims(np.asarray(img, dtype=np.uint8), axis=0)

        self._interp.set_tensor(self._input["index"], batch)
        self._interp.invoke()

        n = int(np.asarray(self._interp.get_tensor(self._count["index"])).reshape(-1)[0])
        classes = np.asarray(self._interp.get_tensor(self._classes["index"])).reshape(-1)[:n]
        scores = np.asarray(self._interp.get_tensor(self._scores["index"])).reshape(-1)[:n]

        birds = np.flatnonzero(np.rint(classes).astype(int) == BIRD_CLASS_ID)
        if birds.size == 0:
            return None
        best = int(birds[np.argmax(scores[birds])])
        if float(scores[best]) < self._threshold:
            return None
        boxes = np.asarray(self._interp.get_tensor(self._boxes["index"])).reshape(-1, 4)
        return Detection(float(scores[best]), _to_box(boxes[best]))
