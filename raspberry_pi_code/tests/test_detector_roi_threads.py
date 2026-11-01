"""The detector's thread count and the CAMERA_ROI crop.

Fakes only. The Pi benchmark measures the speed-up. These tests pin the wiring:
the setting reaches the interpreter, a bad region stops the service at config
load, and the crop lands on the right pixels.
"""
import asyncio
import types

import numpy as np
import pytest

from raspberry_pi_code.config import FULL_FRAME, Config, parse_roi
from raspberry_pi_code.main import _build_trigger
from raspberry_pi_code.tests.test_camera_trigger import (
    FakeCamera,
    FakeClock,
    FakeInterpreter,
)
from raspberry_pi_code.trigger import bird_detector
from raspberry_pi_code.trigger.bird_detector import BIRD_CLASS_ID, BirdDetector, Detection
from raspberry_pi_code.trigger.camera_trigger import CameraTrigger, crop

# ── CAMERA_ROI parsing ────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_roi_is_the_full_frame(raw):
    assert parse_roi(raw) == FULL_FRAME


def test_roi_parses_four_fractions():
    assert parse_roi("0.25, 0.1, 0.5,0.6") == (0.25, 0.1, 0.5, 0.6)


def test_roi_may_touch_the_far_edges_despite_float_rounding():
    # 0.3 + 0.7 is 1.0000000000000002 in floating point.
    assert parse_roi("0.3,0.2,0.7,0.8") == (0.3, 0.2, 0.7, 0.8)


@pytest.mark.parametrize(
    "raw",
    [
        "0.5,0.5,0.5",          # three numbers
        "0,0,1,1,1",            # five numbers
        "a,b,c,d",              # not numbers
        "0.1;0.1;0.5;0.5",      # wrong separator
        "-0.1,0,0.5,0.5",       # negative x
        "0,-0.1,0.5,0.5",       # negative y
        "0,0,0,0.5",            # zero width
        "0,0,0.5,-0.5",         # negative height
        "0.6,0,0.5,0.5",        # runs off the right edge
        "0,0.6,0.5,0.5",        # runs off the bottom edge
        "0,0,nan,0.5",          # NaN slips past plain comparisons
        "0,0,inf,0.5",
        "10,10,20,20",          # pixels, not fractions
    ],
)
def test_bad_roi_is_refused(raw):
    with pytest.raises(ValueError, match="CAMERA_ROI"):
        parse_roi(raw)


def test_config_reads_camera_roi_when_built(monkeypatch):
    monkeypatch.setenv("CAMERA_ROI", "0.2,0.3,0.4,0.5")

    assert Config().camera_roi == (0.2, 0.3, 0.4, 0.5)


def test_config_refuses_to_build_on_a_bad_roi(monkeypatch):
    """main.py builds Config() first, so this is the service refusing to start."""
    monkeypatch.setenv("CAMERA_ROI", "0.5,0.5,0.8,0.8")

    with pytest.raises(ValueError, match="CAMERA_ROI"):
        Config()


def test_config_defaults_to_the_full_frame(monkeypatch):
    monkeypatch.delenv("CAMERA_ROI", raising=False)

    assert Config().camera_roi == FULL_FRAME


# ── Crop maths ────────────────────────────────────────────────────────────────


def _coords(shape) -> np.ndarray:
    """A frame where each pixel holds (row, col), so a crop shows where it came from."""
    h, w = shape
    rows, cols = np.mgrid[0:h, 0:w]
    return np.stack([rows, cols], axis=-1)


def test_full_frame_returns_the_frame_itself():
    frame = np.zeros((240, 320), np.uint8)

    assert crop(frame, FULL_FRAME) is frame


def test_crop_on_the_main_stream():
    out = crop(_coords((1080, 1920)), (0.25, 0.5, 0.5, 0.25))

    assert out.shape[:2] == (270, 960)
    assert tuple(out[0, 0]) == (540, 480)
    assert tuple(out[-1, -1]) == (809, 1439)


def test_same_fractions_crop_the_same_scene_on_the_lores_stream():
    """Lores is 320x240 (4:3) and main is 1920x1080 (16:9). Both cover the
    sensor's full field of view, so one set of fractions fits both."""
    out = crop(_coords((240, 320)), (0.25, 0.5, 0.5, 0.25))

    assert out.shape[:2] == (60, 160)
    assert tuple(out[0, 0]) == (120, 80)


def test_crop_keeps_the_colour_channels():
    out = crop(np.zeros((1080, 1920, 3), np.uint8), (0.0, 0.0, 0.5, 0.5))

    assert out.shape == (540, 960, 3)


def test_crop_edges_round_to_the_nearest_pixel():
    # 1/3 of 100 is 33.3, and 2/3 of 100 is 66.7.
    out = crop(_coords((100, 100)), (1 / 3, 1 / 3, 1 / 3, 1 / 3))

    assert out.shape[:2] == (34, 34)
    assert tuple(out[0, 0]) == (33, 33)


def test_tiny_roi_still_yields_one_pixel():
    out = crop(_coords((240, 320)), (0.999, 0.999, 0.001, 0.001))

    assert out.shape[:2] == (1, 1)
    assert tuple(out[0, 0]) == (239, 319)


def test_cropped_view_feeds_the_detector():
    """The crop is a non-contiguous view. The detector must accept it."""
    det = BirdDetector("unused.tflite", 0.5)
    interp = FakeInterpreter([(BIRD_CLASS_ID, 0.8)])
    assert det.attach(interp)

    view = crop(np.zeros((1080, 1920, 3), np.uint8), (0.1, 0.1, 0.3, 0.6))

    assert det.detect(view).score == pytest.approx(0.8)
    assert interp.input_seen.shape == (1, 320, 320, 3)


# ── The trigger applies the region to both streams ────────────────────────────


class RecordingDetector:
    """Says "bird" every time and records the frame shape it was given."""

    def __init__(self):
        self.shapes: list[tuple] = []

    def load(self):
        return True

    def detect(self, rgb):
        self.shapes.append(rgb.shape)
        return Detection(0.9, None)

    def detections(self, rgb):
        return [self.detect(rgb)]


class FullSizeCamera(FakeCamera):
    """FakeCamera with a full-size main stream."""

    async def grab_rgb(self):
        self.rgb_grabs += 1
        return np.zeros((1080, 1920, 3), np.uint8)


def _left_half_flicker(n: int) -> list[np.ndarray]:
    """Lores frames whose left half changes every frame. The right half is still."""
    frames = []
    for i in range(n):
        frame = np.full((240, 320), 100, np.uint8)
        frame[:, :160] = 50 if i % 2 else 200
        frames.append(frame)
    return frames


def _roi_trigger(camera, detector, roi):
    return CameraTrigger(
        camera,
        detector,
        motion_threshold=0.01,
        quiet_gap_seconds=15,
        analysis_fps=5,
        roi=roi,
        clock=FakeClock(),
    )


def test_motion_outside_the_roi_does_not_wake_the_detector():
    camera = FullSizeCamera(_left_half_flicker(4))
    detector = RecordingDetector()
    trigger = _roi_trigger(camera, detector, (0.5, 0.0, 0.5, 1.0))

    async def run():
        return [await trigger.step() for _ in range(4)]

    assert asyncio.run(run()) == [False] * 4
    assert detector.shapes == []
    assert camera.rgb_grabs == 0


def test_motion_inside_the_roi_runs_the_detector_on_the_crop():
    camera = FullSizeCamera(_left_half_flicker(3))
    detector = RecordingDetector()
    trigger = _roi_trigger(camera, detector, (0.0, 0.25, 0.5, 0.5))

    async def run():
        return [await trigger.step() for _ in range(2)]

    assert asyncio.run(run()) == [False, True]
    assert detector.shapes == [(540, 960, 3)]


# ── DETECTOR_THREADS reaches the interpreter ──────────────────────────────────


def _fake_runtime(created: list):
    """A stand-in for the module import_tflite returns. Records constructor args."""

    class Interpreter(FakeInterpreter):
        def __init__(self, model_path=None, num_threads=None):
            created.append({"model_path": model_path, "num_threads": num_threads})
            super().__init__([])

    return types.SimpleNamespace(Interpreter=Interpreter)


@pytest.fixture
def model_file(tmp_path):
    path = tmp_path / "det.tflite"
    path.write_bytes(b"")
    return str(path)


@pytest.mark.parametrize("threads", [1, 4])
def test_num_threads_reaches_the_interpreter(model_file, monkeypatch, threads):
    created: list = []
    monkeypatch.setattr(bird_detector, "import_tflite", lambda: _fake_runtime(created))

    assert BirdDetector(model_file, 0.5, num_threads=threads).load() is True
    assert created == [{"model_path": model_file, "num_threads": threads}]


def test_detector_defaults_to_four_threads(model_file, monkeypatch):
    created: list = []
    monkeypatch.setattr(bird_detector, "import_tflite", lambda: _fake_runtime(created))

    assert BirdDetector(model_file, 0.5).load() is True
    assert created[0]["num_threads"] == 4


@pytest.mark.parametrize("threads", [0, -1])
def test_detector_refuses_fewer_than_one_thread(threads):
    with pytest.raises(ValueError, match="DETECTOR_THREADS"):
        BirdDetector("unused.tflite", 0.5, num_threads=threads)


def test_build_trigger_passes_threads_and_roi_through(model_file, monkeypatch):
    created: list = []
    monkeypatch.setattr(bird_detector, "import_tflite", lambda: _fake_runtime(created))
    config = Config(
        trigger_type="camera",
        detector_model_path=model_file,
        detector_threads=3,
        camera_roi=(0.1, 0.2, 0.3, 0.4),
    )

    trigger = _build_trigger(config, FakeCamera())

    assert trigger._roi == (0.1, 0.2, 0.3, 0.4)
    assert trigger._detector.load() is True
    assert created[0]["num_threads"] == 3


def test_detector_threads_setting_defaults_to_four():
    assert Config().detector_threads == 4
