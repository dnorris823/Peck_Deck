"""Camera trigger: watch the feed, confirm a bird or an animal, fire once per visit.

Each analysis tick runs three steps:

1. Motion check. Frame differencing on the small greyscale lores frame. Cheap,
   so it runs on every tick.
2. Detector. A COCO detector on the main frame, for the classes in
   ``ANIMAL_CLASS_IDS``. It runs only after motion, or while a visit is open,
   so the Pi CPU stays mostly idle.
3. Visit rule. A detection fires a trigger event only if its group saw nothing
   in the previous ``quiet_gap_seconds``. There are two groups, birds and
   everything else, each with its own ``VisitTracker``. With one tracker, a
   squirrel that camps on the feeder for an hour would hide every bird that
   lands beside it.

The motion fallback, behind ``CAMERA_MOTION_CAPTURE``, catches the animals the
detector misses. When motion lasts ``motion_capture_seconds`` with no detection
and no open visit, it fires one event marked ``trigger="motion"`` and opens a
visit in the animal group, so it does not repeat until the gap passes.

The motion check and the detector see only the region of interest,
``CAMERA_ROI``. It is in fractions of the frame, so one setting crops both the
lores and the main stream. The detector's box comes back in fractions of the
crop, so the trigger maps it to the full frame before it hands it on.

The visit rule is the only repeat rule. The pipeline applies none of its own.

Each tick that gets a frame also sets the tick age, ``tick_age()``. The Pi sends
it in every heartbeat as ``trigger_age_seconds``, and the backend's feed check
skips a feeder whose tick is over 10 minutes old. See backend/feed/monitor.py.
A tick means "a frame was analysed", whatever the detector found. That keeps
the age true on a quiet feeder, and it must stay true if the trigger fires on
more classes than birds. A trigger that stops ticking turns off the feeder's
"out" alert, so a crashed trigger never reads as empty feed.
"""

import asyncio
import logging
import time
from typing import Callable

import numpy as np

from ..bird_crop import to_frame
from ..camera.base import CameraBase
from ..config import FULL_FRAME
from .base import TriggerBase, TriggerEvent
from .bird_detector import BIRD_CLASS_ID, BirdDetector, Detection

logger = logging.getLogger(__name__)

# A pixel counts as changed when its grey level moves by more than this. It sits
# above sensor noise on the lores stream and below a bird's edge contrast.
PIXEL_DELTA = 25
# Motion counts as one run through still ticks up to this long. A squirrel that
# pauses to eat still moves most ticks, not every tick.
MOTION_HOLD_SECONDS = 1.0

BIRDS = "bird"
ANIMALS = "animal"


def group_of(class_id: int | None) -> str:
    """The visit group of a COCO class: birds, or every other animal."""
    return BIRDS if class_id == BIRD_CLASS_ID else ANIMALS


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
    """One visit = the first detection after a quiet gap, for one group."""

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
        motion_capture: bool = False,
        motion_capture_seconds: float = 3.0,
    ):
        if analysis_fps <= 0:
            raise ValueError(f"CAMERA_ANALYSIS_FPS must be above 0, got {analysis_fps}")
        if motion_capture_seconds <= 0:
            raise ValueError(
                f"CAMERA_MOTION_CAPTURE_SECONDS must be above 0, got {motion_capture_seconds}"
            )
        self._camera = camera
        self._detector = detector
        self._motion = MotionDetector(motion_threshold)
        self._visits = {BIRDS: VisitTracker(quiet_gap_seconds), ANIMALS: VisitTracker(quiet_gap_seconds)}
        self._motion_capture = motion_capture
        self._motion_capture_seconds = motion_capture_seconds
        # The current run of motion: when it started, and the last moving tick.
        self._motion_start: float | None = None
        self._motion_last: float | None = None
        self._interval = 1.0 / analysis_fps
        self._roi = roi
        self._clock = clock
        self._queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._last_tick: float | None = None

    def tick_age(self) -> float | None:
        """Seconds since the last tick that analysed a frame. None before one.

        The heartbeat reports it. The heartbeat proves the process is alive, and
        this proves the trigger still watches. Without it, a crashed trigger
        reads on the backend as a feeder with no visits, which is empty feed.
        """
        if self._last_tick is None:
            return None
        return max(0.0, self._clock() - self._last_tick)

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

    async def next_event(self) -> TriggerEvent:
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

    def _in_visit(self, now: float) -> bool:
        return any(v.in_visit(now) for v in self._visits.values())

    def _track_motion(self, moved: bool, now: float) -> None:
        if not moved:
            if self._motion_last is not None and now - self._motion_last > MOTION_HOLD_SECONDS:
                self._motion_start = self._motion_last = None
            return
        if self._motion_start is None:
            self._motion_start = now
        self._motion_last = now

    async def step(self) -> bool:
        """Run one analysis tick. Returns True when it fired a trigger event."""
        gray = await self._camera.grab_gray()
        if gray is None:
            return False
        # Before the motion check and the detector, so every analysed frame
        # counts, with or without motion or a detection of any class. Nothing
        # else sets it, so the motion fallback never fakes a tick.
        self._last_tick = self._clock()
        moved = self._motion.update(crop(gray, self._roi))
        now = self._clock()
        self._track_motion(moved, now)

        # While a visit is open, run the detector even without motion. A bird
        # that sits still to eat is still there, and the visit must stay open.
        if not moved and not self._in_visit(now):
            return False

        rgb = await self._camera.grab_rgb()
        if rgb is None:
            return False
        found = await asyncio.to_thread(self._detector.detections, crop(rgb, self._roi))

        # The best detection per group. A bird beside a camping squirrel still
        # counts, because birds keep their own visit.
        best: dict[str, Detection] = {}
        for detection in found:
            best.setdefault(group_of(detection.class_id), detection)
        fired = False
        for group, detection in best.items():
            if self._visits[group].bird_seen(now):
                self._fire(detection, group)
                fired = True
        if not found and moved:
            fired = self._maybe_motion_capture(now) or fired
        return fired

    def _fire(self, detection: Detection, group: str) -> None:
        box = None if detection.box is None else to_frame(detection.box, self._roi)
        logger.info(
            "%s detected (class %d, score %.2f, box %s). Starting a new visit",
            "Bird" if group == BIRDS else "Animal",
            detection.class_id,
            detection.score,
            "none" if box is None else ",".join(f"{v:.3f}" for v in box),
        )
        self._queue.put_nowait(
            TriggerEvent(asyncio.get_running_loop().time(), box, detection.class_id)
        )

    def _maybe_motion_capture(self, now: float) -> bool:
        """Fire a motion capture when motion has lasted long enough unexplained."""
        if not self._motion_capture or self._motion_start is None:
            return False
        if now - self._motion_start < self._motion_capture_seconds or self._in_visit(now):
            return False
        logger.info(
            "Motion for %.1f s with no detection. Capturing one frame for Tier 2",
            now - self._motion_start,
        )
        # Opens an animal visit, so a long run of motion captures once per gap.
        self._visits[ANIMALS].bird_seen(now)
        self._motion_start = self._motion_last = None
        self._queue.put_nowait(
            TriggerEvent(asyncio.get_running_loop().time(), None, None, trigger="motion")
        )
        return True
