"""The classifiers see a crop around the detector's bird box.

The camera is the 120° wide IMX708, so a bird fills a small part of each frame.
On 2026-10-28 Tier 1 called a clear house finch "Background (92%)" because the
dark room filled the frame. The box travels detector → trigger → pipeline, and
the classifiers get a square crop. The sighting keeps the full frame.
"""
import asyncio
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from raspberry_pi_code.api_client import UploadOutcome
from raspberry_pi_code.bird_crop import square_around, to_frame, write_crop
from raspberry_pi_code.classification.base import ClassificationResult, ClassifierBase
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline
from raspberry_pi_code.tests.test_camera_trigger import (
    FakeClock,
    FakeDetector,
    FakeInterpreter,
)
from raspberry_pi_code.tests.test_detector_roi_threads import FullSizeCamera
from raspberry_pi_code.trigger.bird_detector import BIRD_CLASS_ID, BirdDetector
from raspberry_pi_code.trigger.camera_trigger import CameraTrigger

# ── The crop maths ────────────────────────────────────────────────────────────


def test_square_is_centred_on_the_box_with_the_margin():
    # A 200 x 100 px box centred at (960, 540). Longer side 200, plus 25% each side.
    box = (860 / 1920, 490 / 1080, 200 / 1920, 100 / 1080)

    assert square_around(1920, 1080, box, 0.25) == (810, 390, 1110, 690)


def test_zero_margin_is_the_box_s_longer_side():
    box = (100 / 1920, 200 / 1080, 50 / 1920, 80 / 1080)

    left, top, right, bottom = square_around(1920, 1080, box, 0.0)

    assert (right - left, bottom - top) == (80, 80)
    assert (left, top) == (85, 200)


def test_box_at_the_left_top_corner_slides_the_square_inside():
    box = (0.0, 0.0, 100 / 1920, 100 / 1080)

    assert square_around(1920, 1080, box, 0.5) == (0, 0, 200, 200)


def test_box_at_the_right_bottom_corner_slides_the_square_inside():
    box = (1820 / 1920, 980 / 1080, 100 / 1920, 100 / 1080)

    assert square_around(1920, 1080, box, 0.5) == (1720, 880, 1920, 1080)


def test_square_larger_than_the_frame_shrinks_to_its_shorter_side():
    box = (0.2, 0.0, 0.6, 1.0)

    left, top, right, bottom = square_around(1920, 1080, box, 0.25)

    assert (top, bottom) == (0, 1080)
    assert right - left == 1080
    assert left == 420, "still centred on the box"


def test_tiny_box_still_yields_one_pixel():
    assert square_around(1920, 1080, (0.5, 0.5, 1e-9, 1e-9), 0.0) == (960, 540, 961, 541)


@pytest.mark.parametrize(
    "box",
    [(0.0, 0.0, 0.01, 0.01), (0.99, 0.99, 0.01, 0.01), (0.0, 0.4, 0.3, 0.3), (0.9, 0.0, 0.1, 0.9)],
)
def test_square_always_lies_inside_the_frame(box):
    left, top, right, bottom = square_around(1920, 1080, box, 0.25)

    assert 0 <= left < right <= 1920
    assert 0 <= top < bottom <= 1080
    assert right - left == bottom - top


def test_box_in_the_roi_maps_to_the_full_frame():
    roi = (0.5, 0.25, 0.5, 0.5)

    assert to_frame((0.5, 0.5, 0.2, 0.4), roi) == pytest.approx((0.75, 0.5, 0.1, 0.2))


def test_full_frame_roi_leaves_the_box_alone():
    assert to_frame((0.1, 0.2, 0.3, 0.4), (0.0, 0.0, 1.0, 1.0)) == pytest.approx(
        (0.1, 0.2, 0.3, 0.4)
    )


def test_write_crop_saves_the_pixels_inside_the_box(tmp_path):
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[490:590, 910:1010] = (255, 0, 0)  # a red "bird", 100 px square
    src = tmp_path / "frame.png"
    Image.fromarray(frame).save(src)

    size = write_crop(
        src, tmp_path / "crops" / "c.jpg", (910 / 1920, 490 / 1080, 100 / 1920, 100 / 1080),
        0.0, 95,
    )

    assert size == (100, 100)
    out = np.asarray(Image.open(tmp_path / "crops" / "c.jpg"))
    assert out[50, 50, 0] > 200 and out[50, 50, 1] < 60


# ── The detector returns the box ──────────────────────────────────────────────


def test_detector_returns_the_best_bird_s_box_as_x_y_width_height():
    det = BirdDetector("unused.tflite", 0.5)
    assert det.attach(FakeInterpreter([
        (BIRD_CLASS_ID, 0.6, [0.0, 0.0, 0.1, 0.1]),
        (BIRD_CLASS_ID, 0.9, [0.2, 0.4, 0.6, 0.5]),  # ymin, xmin, ymax, xmax
    ]))

    found = det.detect(np.zeros((1080, 1920, 3), np.uint8))

    assert found.score == pytest.approx(0.9)
    assert found.box == pytest.approx((0.4, 0.2, 0.1, 0.4))


def test_detector_clips_a_box_that_spills_past_the_frame():
    det = BirdDetector("unused.tflite", 0.5)
    assert det.attach(FakeInterpreter([(BIRD_CLASS_ID, 0.9, [-0.1, 0.8, 0.5, 1.2])]))

    found = det.detect(np.zeros((1080, 1920, 3), np.uint8))

    assert found.box == pytest.approx((0.8, 0.0, 0.2, 0.5))


def test_detector_gives_no_box_for_an_empty_one():
    det = BirdDetector("unused.tflite", 0.5)
    assert det.attach(FakeInterpreter([(BIRD_CLASS_ID, 0.9)]))

    assert det.detect(np.zeros((1080, 1920, 3), np.uint8)).box is None


# ── The trigger maps the box through CAMERA_ROI ───────────────────────────────


def test_trigger_event_carries_the_box_in_full_frame_fractions():
    frames = [np.full((240, 320), 50 if i % 2 else 200, np.uint8) for i in range(3)]
    trigger = CameraTrigger(
        FullSizeCamera(frames),
        FakeDetector(0.9, box=(0.5, 0.5, 0.2, 0.4)),
        motion_threshold=0.01,
        quiet_gap_seconds=15,
        analysis_fps=5,
        roi=(0.5, 0.25, 0.5, 0.5),
        clock=FakeClock(),
    )

    async def run():
        fired = [await trigger.step() for _ in range(2)]
        return fired, trigger._queue.get_nowait()

    fired, event = asyncio.run(run())

    assert fired == [False, True]
    assert event.box == pytest.approx((0.75, 0.5, 0.1, 0.2))


# ── The pipeline classifies the crop and stores the full frame ────────────────


class _PhotoCamera:
    """Saves a real 1920 x 1080 JPEG where the pipeline asks."""

    async def capture(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), (80, 120, 80)).save(output_path, "JPEG")
        return output_path


class _SizeRecordingTier(ClassifierBase):
    """Records the size and path of each image it is asked to classify."""

    def __init__(self, tier: str):
        self._tier = tier
        self.seen: list[tuple[Path, tuple[int, int]]] = []

    @property
    def tier_name(self) -> str:
        return self._tier

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        with Image.open(image_path) as img:
            self.seen.append((image_path, img.size))
        return ClassificationResult("House Finch", "Haemorhous mexicanus", 0.1, self._tier)


class _RecordingClient:
    def __init__(self):
        self.posts: list[dict] = []

    async def post_sighting(self, **kwargs) -> UploadOutcome:
        self.posts.append(kwargs)
        return UploadOutcome.OK


def _pipeline(tmp_path) -> tuple[Pipeline, list[_SizeRecordingTier], _RecordingClient]:
    cfg = Config(cache_dir=str(tmp_path / "cache"), device_token="t", classify_crop_margin=0.25)
    pipeline = Pipeline(cfg, camera=_PhotoCamera(), debounce_seconds=0)
    pipeline._cache.setup()
    tiers = [_SizeRecordingTier("gpu"), _SizeRecordingTier("local")]
    pipeline._classifiers_for_preference = lambda: tiers
    client = _RecordingClient()
    pipeline._client = client
    return pipeline, tiers, client


def _visit(pipeline: Pipeline, box) -> None:
    async def run():
        await pipeline.handle_trigger(box)
        await pipeline._process(pipeline._work.get_nowait())

    asyncio.run(run())


def test_both_tiers_classify_the_crop_and_the_sighting_keeps_the_full_frame(tmp_path):
    pipeline, tiers, client = _pipeline(tmp_path)
    # 200 x 100 px box: a 300 px square with the 25% margin.
    _visit(pipeline, (860 / 1920, 490 / 1080, 200 / 1920, 100 / 1080))

    for tier in tiers:
        assert [size for _, size in tier.seen] == [(300, 300)]
    posted = client.posts[0]["image_path"]
    assert Image.open(posted).size == (1920, 1080)
    assert all(path != posted for tier in tiers for path, _ in tier.seen)


def test_the_crop_file_is_deleted_after_classification(tmp_path):
    pipeline, tiers, _ = _pipeline(tmp_path)
    _visit(pipeline, (0.4, 0.4, 0.1, 0.1))

    crop_path = tiers[0].seen[0][0]
    assert not crop_path.exists()
    assert list(pipeline._cache._images.glob("*.jpg")) != [], "the full frame stays"


def test_no_box_classifies_the_full_frame(tmp_path):
    pipeline, tiers, client = _pipeline(tmp_path)
    _visit(pipeline, None)

    assert tiers[0].seen == [(client.posts[0]["image_path"], (1920, 1080))]


def test_a_crop_that_fails_falls_back_to_the_full_frame(tmp_path):
    pipeline, tiers, client = _pipeline(tmp_path)

    async def broken_jpeg(output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\xff\xd8 not really a jpeg")
        return output_path

    pipeline._camera.capture = broken_jpeg
    pipeline._classifiers_for_preference = lambda: [_PathOnlyTier()]
    _visit(pipeline, (0.4, 0.4, 0.1, 0.1))

    assert len(client.posts) == 1, "a failed crop must not lose the visit"
    assert client.posts[0]["tier_used"] == "gpu"


class _PathOnlyTier(ClassifierBase):
    """Answers without opening the image."""

    @property
    def tier_name(self) -> str:
        return "gpu"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        return ClassificationResult("House Finch", "Haemorhous mexicanus", 0.9, "gpu")
