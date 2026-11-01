"""COCO object detector: is there a bird, or an animal, in this frame.

The model is EfficientDet-Lite0 from `scripts/fetch_models.py`. It runs on the
same TFLite runtime as Tier 1. It does not name the species. Tier 2 does that
after the capture.

COCO has no squirrel class. A squirrel scores as bird, cat, dog or bear about a
third of the time (machine_learning/MODELS.md, *Feeder animals*), so the
detector watches the classes in ``ANIMAL_CLASS_IDS``, not only bird.
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
CAT_CLASS_ID = 16
DOG_CLASS_ID = 17
BEAR_CLASS_ID = 22


class Detection(NamedTuple):
    """The best detection of one class in a frame.

    ``box`` is in fractions of the frame the detector was given. It is None
    when the model returned an empty box.
    """

    score: float
    box: Box | None
    class_id: int = BIRD_CLASS_ID


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

    def __init__(
        self,
        model_path: str,
        score_threshold: float,
        num_threads: int = 4,
        class_ids: tuple[int, ...] = (BIRD_CLASS_ID,),
    ):
        if num_threads < 1:
            raise ValueError(f"DETECTOR_THREADS must be 1 or more, got {num_threads}")
        if not class_ids:
            raise ValueError("ANIMAL_CLASS_IDS must name at least one class")
        self._model_path = model_path
        self._threshold = score_threshold
        self._class_ids = frozenset(class_ids)
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
        """Return the best detection of a watched class at or above the threshold.

        None when there is none. ``rgb`` is an (h, w, 3) uint8 frame of any
        size. Blocking: call it through ``asyncio.to_thread``.
        """
        found = self.detections(rgb)
        return found[0] if found else None

    def detections(self, rgb: np.ndarray) -> list[Detection]:
        """The best detection of each watched class at or above the threshold.

        Best score first. The camera trigger keeps a visit per group, so it
        needs the bird even when a squirrel scored higher. Blocking, like
        ``detect``.
        """
        if self._interp is None:
            return []

        classes, scores = self._run(rgb)
        best: dict[int, int] = {}
        for i, cls in enumerate(classes.tolist()):
            if cls in self._class_ids and scores[i] >= self._threshold:
                if cls not in best or scores[i] > scores[best[cls]]:
                    best[cls] = i
        if not best:
            return []
        boxes = np.asarray(self._interp.get_tensor(self._boxes["index"])).reshape(-1, 4)
        found = [Detection(float(scores[i]), _to_box(boxes[i]), cls) for cls, i in best.items()]
        return sorted(found, key=lambda d: -d.score)

    def scores_by_class(self, rgb: np.ndarray) -> dict[int, float]:
        """The best score for every COCO class the model reported, any score.

        ``scripts/validate_animals.py`` uses it to see what the detector calls a
        squirrel. Blocking, like ``detect``.
        """
        if self._interp is None:
            return {}
        classes, scores = self._run(rgb)
        best: dict[int, float] = {}
        for cls, score in zip(classes.tolist(), scores.tolist()):
            best[cls] = max(best.get(cls, 0.0), float(score))
        return best

    def _run(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Run the model on one frame. Returns the class ids and their scores."""
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
        return np.rint(classes).astype(int), scores
