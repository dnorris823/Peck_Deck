"""Camera trigger: watch the feed, confirm a bird, fire once per visit.

Each analysis tick runs three steps:

1. Motion check. Frame differencing on the small greyscale lores frame. Cheap,
   so it runs on every tick.
2. Bird detector. A COCO detector on the main frame. It runs only after motion,
   or while a visit is open, so the Pi CPU stays mostly idle.
3. Visit rule. A bird detection fires a trigger event only if no bird was
   detected in the previous ``quiet_gap_seconds``.

The motion check and the detector see only the region of interest,
``CAMERA_ROI``. It is in fractions of the frame, so one setting crops both the
lores and the main stream.

The visit rule is the only repeat rule for this trigger. ``main.py`` sets the
pipeline's own debounce to 0 when this trigger runs, so the two cannot disagree.
"""

import asyncio
import logging
import time
from typing import Callable

import numpy as np

from ..camera.base import CameraBase
from ..config import FULL_FRAME
from .base import TriggerBase
from .bird_detector import BirdDetector

logger = logging.getLogger(__name__)

# A pixel counts as changed when its grey level moves by more than this. It sits
# above sensor noise on the lores stream and below a bird's edge contrast.
PIXEL_DELTA = 25


def crop(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    """Return the part of ``frame`` that ``roi`` covers, as a view.

    ``roi`` is (x, y, width, height) in fractions of the frame. Edges round to
    the nearest pixel, and the crop is never less than one pixel each way.
    """
    if roi == FULL_FRAME:
        return frame
    x, y, w, h = roi
    frame_h, frame_w = frame.shape[:2]
    x0 = min(int(round(x * frame_w)), frame_w - 1)
    y0 = min(int(round(y * frame_h)), frame_h - 1)
    x1 = max(int(round((x + w) * frame_w)), x0 + 1)
    y1 = max(int(round((y + h) * frame_h)), y0 + 1)
    return frame[y0:y1, x0:x1]


class MotionDetector:
    """Frame differencing against the previous frame."""

    def __init__(self, threshold: float, pixel_delta: int = PIXEL_DELTA):
        """``threshold`` is the fraction of pixels (0 to 1) that must change."""
        self._threshold = threshold
        self._pixel_delta = pixel_delta
        self._prev: np.ndarray | None = None

    def update(self, gray: np.ndarray) -> bool:
        """Feed the next greyscale frame. Returns True when it moved enough.

        The first frame, and a frame whose size changed, only set the baseline.
        """
        cur = gray.astype(np.int16)
        prev, self._prev = self._prev, cur
        if prev is None or prev.shape != cur.shape:
            return False
        changed = np.abs(cur - prev) > self._pixel_delta
        return float(changed.mean()) >= self._threshold


class VisitTracker:
    """One visit = the first bird detection after a quiet gap."""

    def __init__(self, quiet_gap_seconds: float):
        self._gap = quiet_gap_seconds
        self._last_bird: float | None = None

    def bird_seen(self, now: float) -> bool:
        """Record a detection. Returns True when it starts a new visit."""
        new_visit = self._last_bird is None or now - self._last_bird >= self._gap
        self._last_bird = now
        return new_visit

    def in_visit(self, now: float) -> bool:
        """True while the last detection is less than the quiet gap ago."""
        return self._last_bird is not None and now - self._last_bird < self._gap


class CameraTrigger(TriggerBase):
    """Fires when the camera sees a new bird visit. No GPIO involved."""

    debounces_itself = True

    def __init__(
        self,
        camera: CameraBase,
        detector: BirdDetector,
        *,
        motion_threshold: float,
        quiet_gap_seconds: float,
        analysis_fps: float,
        roi: tuple[float, float, float, float] = FULL_FRAME,
        clock: Callable[[], float] = time.monotonic,
    ):
        if analysis_fps <= 0:
            raise ValueError(f"CAMERA_ANALYSIS_FPS must be above 0, got {analysis_fps}")
        self._camera = camera
        self._detector = detector
        self._motion = MotionDetector(motion_threshold)
        self._visits = VisitTracker(quiet_gap_seconds)
        self._interval = 1.0 / analysis_fps
        self._roi = roi
        self._clock = clock
        self._queue: asyncio.Queue[float] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "CameraTrigger":
        if await self._camera.grab_gray() is None:
            logger.warning("Camera is not streaming. The camera trigger will fire "
                           "no events")
            return self
        if not await asyncio.to_thread(self._detector.load):
            logger.warning("Bird detector unavailable. The camera trigger will fire "
                           "no events")
            return self
        self._task = asyncio.create_task(self._watch(), name="camera-trigger")
        logger.info("Camera trigger active")
        return self

    async def __aexit__(self, *args) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def next_event(self) -> float:
        return await self._queue.get()

    async def _watch(self) -> None:
        while True:
            started = self._clock()
            try:
                await self.step()
            except Exception:
                # One bad frame must not end the trigger for the rest of the run.
                logger.exception("Camera trigger analysis failed")
            elapsed = self._clock() - started
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def step(self) -> bool:
        """Run one analysis tick. Returns True when it fired a trigger event."""
        gray = await self._camera.grab_gray()
        if gray is None:
            return False
        moved = self._motion.update(crop(gray, self._roi))

        # While a visit is open, run the detector even without motion. A bird
        # that sits still to eat is still there, and the visit must stay open.
        if not moved and not self._visits.in_visit(self._clock()):
            return False

        rgb = await self._camera.grab_rgb()
        if rgb is None:
            return False
        score = await asyncio.to_thread(self._detector.detect, crop(rgb, self._roi))
        if score is None:
            return False

        if not self._visits.bird_seen(self._clock()):
            return False
        logger.info("Bird detected (score %.2f). Starting a new visit", score)
        self._queue.put_nowait(asyncio.get_running_loop().time())
        return True
