"""Camera trigger: motion check, bird detector, visit rule, and wiring.

Every test uses fakes. No camera, no TFLite runtime. The desk test on
the Pi covers the hardware.
"""
import asyncio
import os
from pathlib import Path

import numpy as np
import pytest

from raspberry_pi_code.camera.base import CameraBase
from raspberry_pi_code.config import Config
from raspberry_pi_code.main import _build_trigger
from raspberry_pi_code.pipeline import Capture, Pipeline
from raspberry_pi_code.trigger.bird_detector import BIRD_CLASS_ID, BirdDetector
from raspberry_pi_code.trigger.camera_trigger import (
    CameraTrigger,
    MotionDetector,
    VisitTracker,
)

PERSON = 0
CAT = 16


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeCamera(CameraBase):
    """Serves greyscale frames from a list. An empty list means "not streaming"."""

    def __init__(self, grays: list[np.ndarray] | None = None):
        self.grays = list(grays or [])
        self.rgb_grabs = 0
        self.captured: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def capture(self, output_path):
        self.captured.append(output_path)
        return output_path

    async def grab_gray(self):
        if not self.grays:
            return None
        return self.grays.pop(0) if len(self.grays) > 1 else self.grays[0]

    async def grab_rgb(self):
        self.rgb_grabs += 1
        return np.zeros((48, 64, 3), np.uint8)


class FakeDetector:
    """Stands in for BirdDetector. ``score`` is what detect() returns."""

    def __init__(self, score: float | None = 0.9, loads: bool = True):
        self.score = score
        self.loads = loads
        self.calls = 0

    def load(self) -> bool:
        return self.loads

    def detect(self, rgb):
        self.calls += 1
        return self.score


class FakeInterpreter:
    """Minimal TFLite interpreter with detection post-process outputs."""

    def __init__(self, detections, input_shape=(1, 320, 320, 3), input_dtype=np.uint8,
                 n_outputs=4):
        # detections: list of (class_id, score)
        self._detections = detections
        self._input_shape = np.array(input_shape)
        self._input_dtype = input_dtype
        self._n_outputs = n_outputs
        self.input_seen: np.ndarray | None = None
        self._max = 25

    def allocate_tensors(self):
        pass

    def get_input_details(self):
        return [{"index": 0, "shape": self._input_shape, "dtype": self._input_dtype}]

    def get_output_details(self):
        return [{"index": i} for i in range(1, self._n_outputs + 1)]

    def set_tensor(self, index, value):
        self.input_seen = value

    def invoke(self):
        pass

    def get_tensor(self, index):
        classes = np.zeros((1, self._max), np.float32)
        scores = np.zeros((1, self._max), np.float32)
        for i, (cls, score) in enumerate(self._detections):
            classes[0, i] = cls
            scores[0, i] = score
        return {
            1: np.zeros((1, self._max, 4), np.float32),
            2: classes,
            3: scores,
            4: np.array([len(self._detections)], np.float32),
        }[index]


def _frame(value: int = 100, shape=(240, 320)) -> np.ndarray:
    return np.full(shape, value, np.uint8)


def _with_block(base: np.ndarray, fraction: float, value: int = 250) -> np.ndarray:
    """Copy of ``base`` with the top rows changed, covering ``fraction`` of pixels."""
    out = base.copy()
    rows = int(round(base.shape[0] * fraction))
    out[:rows, :] = value
    return out


def _trigger(camera, detector, clock, gap=15.0, motion=0.01):
    return CameraTrigger(
        camera,
        detector,
        motion_threshold=motion,
        quiet_gap_seconds=gap,
        analysis_fps=5,
        clock=clock,
    )


# ── Motion check ──────────────────────────────────────────────────────────────


def test_first_frame_only_sets_the_baseline():
    motion = MotionDetector(threshold=0.01)

    assert motion.update(_frame()) is False


def test_identical_frames_are_not_motion():
    motion = MotionDetector(threshold=0.01)
    motion.update(_frame())

    assert motion.update(_frame()) is False


def test_sensor_noise_below_the_pixel_delta_is_not_motion():
    rng = np.random.default_rng(0)
    base = _frame(100)
    noisy = (base.astype(np.int16) + rng.integers(-10, 11, base.shape)).astype(np.uint8)
    motion = MotionDetector(threshold=0.01)
    motion.update(base)

    assert motion.update(noisy) is False


def test_a_large_change_is_motion():
    base = _frame(100)
    motion = MotionDetector(threshold=0.01)
    motion.update(base)

    assert motion.update(_with_block(base, 0.10)) is True


def test_a_change_smaller_than_the_threshold_is_not_motion():
    base = _frame(100)
    motion = MotionDetector(threshold=0.05)
    motion.update(base)

    assert motion.update(_with_block(base, 0.02)) is False


def test_motion_compares_against_the_previous_frame_not_the_first():
    base = _frame(100)
    moved = _with_block(base, 0.10)
    motion = MotionDetector(threshold=0.01)
    motion.update(base)
    motion.update(moved)

    assert motion.update(moved.copy()) is False, "a scene that stopped changing is still"


def test_a_frame_size_change_resets_the_baseline():
    motion = MotionDetector(threshold=0.01)
    motion.update(_frame(shape=(240, 320)))

    assert motion.update(_frame(value=250, shape=(120, 160))) is False


# ── Bird detector ─────────────────────────────────────────────────────────────


def _detector(detections, threshold=0.5, **interp_kwargs):
    det = BirdDetector("unused.tflite", threshold)
    interp = FakeInterpreter(detections, **interp_kwargs)
    assert det.attach(interp)
    return det, interp


def test_bird_above_the_threshold_returns_its_score():
    det, _ = _detector([(BIRD_CLASS_ID, 0.82)])

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)) == pytest.approx(0.82)


def test_bird_below_the_threshold_returns_none():
    det, _ = _detector([(BIRD_CLASS_ID, 0.31)])

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)) is None


def test_other_classes_never_count_however_confident():
    det, _ = _detector([(PERSON, 0.99), (CAT, 0.95)])

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)) is None


def test_best_bird_wins_among_mixed_detections():
    det, _ = _detector([(PERSON, 0.99), (BIRD_CLASS_ID, 0.40), (BIRD_CLASS_ID, 0.71)])

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)) == pytest.approx(0.71)


def test_slots_past_the_detection_count_are_ignored():
    det, interp = _detector([(BIRD_CLASS_ID, 0.20)])
    # Plant a stale bird in slot 1, beyond count = 1.
    original = interp.get_tensor

    def get_tensor(index):
        value = original(index).copy()
        if index == 2:
            value[0, 1] = BIRD_CLASS_ID
        if index == 3:
            value[0, 1] = 0.99
        return value

    interp.get_tensor = get_tensor

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)) is None


def test_frame_is_resized_to_the_model_input_as_uint8():
    det, interp = _detector([], input_shape=(1, 320, 320, 3))

    det.detect(np.zeros((1080, 1920, 3), np.uint8))

    assert interp.input_seen.shape == (1, 320, 320, 3)
    assert interp.input_seen.dtype == np.uint8


def test_detector_refuses_a_model_without_four_outputs():
    det = BirdDetector("unused.tflite", 0.5)

    assert det.attach(FakeInterpreter([], n_outputs=1)) is False
    assert det.detect(np.zeros((10, 10, 3), np.uint8)) is None


def test_detector_refuses_a_float_input_model():
    det = BirdDetector("unused.tflite", 0.5)

    assert det.attach(FakeInterpreter([], input_dtype=np.float32)) is False


def test_missing_model_file_fails_to_load_without_raising(tmp_path):
    det = BirdDetector(str(tmp_path / "absent.tflite"), 0.5)

    assert det.load() is False
    assert det.loaded is False


# ── Visit rule ────────────────────────────────────────────────────────────────


def test_first_detection_starts_a_visit():
    assert VisitTracker(15).bird_seen(100.0) is True


def test_detection_inside_the_gap_is_the_same_visit():
    visits = VisitTracker(15)
    visits.bird_seen(100.0)

    assert visits.bird_seen(110.0) is False


def test_detection_after_a_quiet_gap_starts_a_new_visit():
    visits = VisitTracker(15)
    visits.bird_seen(100.0)

    assert visits.bird_seen(115.0) is True


def test_the_gap_runs_from_the_last_detection_not_the_first():
    """A bird that stays 60 s is one visit, not four."""
    visits = VisitTracker(15)
    fired = [visits.bird_seen(t) for t in range(100, 161, 10)]

    assert fired == [True] + [False] * 6


def test_in_visit_tracks_the_gap():
    visits = VisitTracker(15)
    assert visits.in_visit(100.0) is False
    visits.bird_seen(100.0)

    assert visits.in_visit(114.9) is True
    assert visits.in_visit(115.0) is False


# ── CameraTrigger.step with an injected clock ─────────────────────────────────


def _moving_frames(n: int) -> list[np.ndarray]:
    """n frames that each differ from the one before."""
    return [_frame(50 if i % 2 else 200) for i in range(n)]


def test_no_motion_means_the_detector_never_runs():
    camera = FakeCamera([_frame()])
    detector = FakeDetector(0.9)
    trigger = _trigger(camera, detector, FakeClock())

    async def run():
        return [await trigger.step() for _ in range(5)]

    assert asyncio.run(run()) == [False] * 5
    assert detector.calls == 0
    assert camera.rgb_grabs == 0


def test_motion_with_a_bird_fires_one_event():
    camera = FakeCamera(_moving_frames(3))
    trigger = _trigger(camera, FakeDetector(0.9), FakeClock())

    async def run():
        fired = [await trigger.step() for _ in range(2)]
        return fired, trigger._queue.qsize()

    fired, queued = asyncio.run(run())
    assert fired == [False, True], "frame 1 is the baseline, frame 2 moved and had a bird"
    assert queued == 1


def test_motion_without_a_bird_fires_nothing():
    """The hand-wave case: plenty of motion, no bird."""
    camera = FakeCamera(_moving_frames(10))
    detector = FakeDetector(None)
    trigger = _trigger(camera, detector, FakeClock())

    async def run():
        return [await trigger.step() for _ in range(10)]

    assert not any(asyncio.run(run()))
    assert detector.calls == 9


def test_bird_inside_the_quiet_gap_does_not_fire_again():
    clock = FakeClock(1000.0)
    camera = FakeCamera(_moving_frames(20))
    trigger = _trigger(camera, FakeDetector(0.9), clock, gap=15)

    async def run():
        await trigger.step()  # baseline
        events = []
        for t in (1000.0, 1005.0, 1010.0, 1024.0):
            clock.now = t
            events.append(await trigger.step())
        clock.now = 1040.0  # 16 s after the last detection
        events.append(await trigger.step())
        return events

    assert asyncio.run(run()) == [True, False, False, False, True]


def test_a_still_bird_keeps_the_visit_open():
    """With no motion, the detector still runs during a visit.

    Without that, a bird that sits still for 15 s would look like a new visit
    the moment it moves again.
    """
    clock = FakeClock(1000.0)
    first = _frame(50)
    moved = _frame(200)
    camera = FakeCamera([first, moved])
    detector = FakeDetector(0.9)
    trigger = _trigger(camera, detector, clock, gap=15)

    async def run():
        await trigger.step()  # baseline
        assert await trigger.step() is True  # moved, bird: visit starts
        # The frame stays at `moved` from here on, so no more motion.
        results = []
        for t in range(1010, 1060, 10):
            clock.now = float(t)
            results.append(await trigger.step())
        return results

    assert asyncio.run(run()) == [False] * 5
    assert detector.calls == 6, "the detector ran on every tick of the open visit"


def test_visit_closes_after_a_quiet_gap_with_no_bird():
    clock = FakeClock(1000.0)
    camera = FakeCamera([_frame(50), _frame(200)])
    detector = FakeDetector(0.9)
    trigger = _trigger(camera, detector, clock, gap=15)

    async def run():
        await trigger.step()
        await trigger.step()  # visit starts at 1000
        detector.score = None  # bird leaves
        clock.now = 1010.0
        await trigger.step()  # still in the visit: detector runs, sees nothing
        calls_in_visit = detector.calls
        clock.now = 1016.0
        await trigger.step()  # visit closed, no motion: detector skipped
        return calls_in_visit, detector.calls

    in_visit, after = asyncio.run(run())
    assert in_visit == 2
    assert after == 2


def test_camera_not_streaming_starts_no_watcher():
    trigger = _trigger(FakeCamera([]), FakeDetector(0.9), FakeClock())

    async def run():
        async with trigger:
            return trigger._task

    assert asyncio.run(run()) is None


def test_detector_that_cannot_load_starts_no_watcher():
    trigger = _trigger(FakeCamera([_frame()]), FakeDetector(loads=False), FakeClock())

    async def run():
        async with trigger:
            return trigger._task

    assert asyncio.run(run()) is None


def test_watcher_delivers_an_event_through_next_event():
    camera = FakeCamera(_moving_frames(50))
    trigger = CameraTrigger(
        camera,
        FakeDetector(0.9),
        motion_threshold=0.01,
        quiet_gap_seconds=15,
        analysis_fps=1000,
    )

    async def run():
        async with trigger:
            return await asyncio.wait_for(trigger.next_event(), timeout=2)

    assert isinstance(asyncio.run(run()), float)


def test_zero_analysis_fps_is_rejected():
    with pytest.raises(ValueError):
        CameraTrigger(FakeCamera(), FakeDetector(), motion_threshold=0.01,
                      quiet_gap_seconds=15, analysis_fps=0)


# ── _build_trigger and the debounce hand-off ──────────────────────────────────


def test_camera_is_the_default_trigger_type():
    if "TRIGGER_TYPE" in os.environ:
        pytest.skip("TRIGGER_TYPE is set in this environment")

    assert Config().trigger_type == "camera"


def test_build_trigger_builds_the_camera_trigger():
    trigger = _build_trigger(Config(trigger_type="camera"), FakeCamera())

    assert type(trigger) is CameraTrigger


def test_camera_trigger_gets_the_configured_settings():
    cfg = Config(
        trigger_type="camera",
        camera_visit_gap_seconds=42,
        camera_analysis_fps=2,
        camera_detection_threshold=0.66,
    )

    trigger = _build_trigger(cfg, FakeCamera())

    assert trigger._visits._gap == 42
    assert trigger._interval == pytest.approx(0.5)
    assert trigger._detector._threshold == 0.66


@pytest.mark.parametrize("bad", ["", "Camera", "pir", "ir_beam", "motion"])
def test_unknown_trigger_type_refuses_to_start(bad):
    with pytest.raises(ValueError, match="TRIGGER_TYPE"):
        _build_trigger(Config(trigger_type=bad), FakeCamera())


def test_the_camera_trigger_debounces_itself():
    assert _build_trigger(Config(trigger_type="camera"), FakeCamera()).debounces_itself


def _counting_pipeline(tmp_path, **kwargs) -> tuple[Pipeline, list]:
    pipeline = Pipeline(
        Config(cache_dir=str(tmp_path / "cache"), device_token="t", debounce_seconds=30),
        **kwargs,
    )
    captures: list = []

    async def fake_capture():
        captures.append(1)
        return Capture(f"e{len(captures)}", "2026-10-28T12:00:00+00:00", Path("x.jpg"))

    pipeline._capture = fake_capture
    return pipeline, captures


def test_pipeline_debounce_drops_a_quick_second_trigger(tmp_path):
    pipeline, captures = _counting_pipeline(tmp_path)

    async def run():
        # Start the clock past the window, so the first trigger is not dropped.
        pipeline._last_capture = asyncio.get_running_loop().time() - 100
        await pipeline.handle_trigger()
        await pipeline.handle_trigger()

    asyncio.run(run())
    assert len(captures) == 1


def test_zero_debounce_lets_the_trigger_decide(tmp_path):
    """The camera trigger's visit gap is the only repeat rule."""
    pipeline, captures = _counting_pipeline(tmp_path, debounce_seconds=0)

    async def run():
        await pipeline.handle_trigger()
        await pipeline.handle_trigger()

    asyncio.run(run())
    assert len(captures) == 2


def test_pipeline_captures_through_the_shared_camera(tmp_path):
    camera = FakeCamera()
    pipeline = Pipeline(
        Config(cache_dir=str(tmp_path / "cache"), device_token="t"), camera=camera
    )
    pipeline._cache.setup()

    asyncio.run(pipeline._capture())
    assert len(camera.captured) == 1
