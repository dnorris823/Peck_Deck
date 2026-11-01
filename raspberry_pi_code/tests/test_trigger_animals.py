"""The trigger fires on animals as well as birds, with one visit per group.

Birds keep their own ``VisitTracker``, and every other class shares one. A
squirrel that camps on the feeder must not hide a bird that lands beside it.
The motion fallback, off by default, captures what the detector misses. And the
tick age the feed alerts read stays the time since the last analysed frame.
"""
import asyncio
from pathlib import Path

import numpy as np
import pytest

from raspberry_pi_code.api_client import UploadOutcome
from raspberry_pi_code.classification.base import (
    AnimalAnswer,
    ClassificationResult,
    ClassifierBase,
)
from raspberry_pi_code.config import Config, parse_class_ids
from raspberry_pi_code.pipeline import Pipeline
from raspberry_pi_code.tests.test_camera_trigger import FakeCamera, FakeClock, FakeInterpreter
from raspberry_pi_code.trigger.bird_detector import (
    BEAR_CLASS_ID,
    BIRD_CLASS_ID,
    CAT_CLASS_ID,
    BirdDetector,
    Detection,
)
from raspberry_pi_code.trigger.camera_trigger import CameraTrigger

PERSON = 0


def _moving_frames(n: int = 400) -> list[np.ndarray]:
    """Grey frames that alternate, so every tick sees motion."""
    return [np.full((24, 32), 50 if i % 2 else 200, np.uint8) for i in range(n)]


class ScriptedDetector:
    """Hands out one list of detections per call, then repeats the last."""

    def __init__(self, *frames: list[Detection]):
        self.frames = list(frames) or [[]]
        self.calls = 0

    def load(self) -> bool:
        return True

    def detections(self, rgb):
        self.calls += 1
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def _trigger(detector, *, clock=None, motion_capture=False, grays=None, gap=15.0):
    return CameraTrigger(
        FakeCamera(grays if grays is not None else _moving_frames()),
        detector,
        motion_threshold=0.01,
        quiet_gap_seconds=gap,
        analysis_fps=5,
        clock=clock or FakeClock(),
        motion_capture=motion_capture,
        motion_capture_seconds=3.0,
    )


def _events(trigger) -> list:
    out = []
    while not trigger._queue.empty():
        out.append(trigger._queue.get_nowait())
    return out


async def _ticks(trigger, clock, n: int, dt: float = 0.2) -> list:
    """Run ``n`` ticks, ``dt`` seconds apart. Returns every event fired."""
    for _ in range(n):
        await trigger.step()
        clock.now += dt
    return _events(trigger)


SQUIRREL_AS_CAT = Detection(0.8, (0.1, 0.1, 0.3, 0.3), CAT_CLASS_ID)
BIRD = Detection(0.6, (0.6, 0.2, 0.1, 0.1), BIRD_CLASS_ID)


# ── The detector ──────────────────────────────────────────────────────────────


def test_detector_watches_its_classes_and_keeps_the_best_of_each():
    det = BirdDetector("unused.tflite", 0.5, class_ids=(BIRD_CLASS_ID, CAT_CLASS_ID))
    assert det.attach(FakeInterpreter([
        (CAT_CLASS_ID, 0.7, [0.1, 0.1, 0.4, 0.4]),
        (CAT_CLASS_ID, 0.9, [0.2, 0.2, 0.5, 0.5]),
        (BIRD_CLASS_ID, 0.6, [0.0, 0.5, 0.2, 0.7]),
        (PERSON, 0.99),  # not watched
        (BEAR_CLASS_ID, 0.95),  # not watched here
        (BIRD_CLASS_ID, 0.3),  # below the threshold
    ]))

    found = det.detections(np.zeros((240, 320, 3), np.uint8))

    assert [(d.class_id, round(d.score, 2)) for d in found] == [(CAT_CLASS_ID, 0.9), (BIRD_CLASS_ID, 0.6)]
    assert det.detect(np.zeros((240, 320, 3), np.uint8)).class_id == CAT_CLASS_ID


def test_detector_default_still_watches_birds_only():
    det = BirdDetector("unused.tflite", 0.5)
    assert det.attach(FakeInterpreter([(CAT_CLASS_ID, 0.9)]))

    assert det.detect(np.zeros((240, 320, 3), np.uint8)) is None


def test_animal_class_ids_default_and_parse():
    assert parse_class_ids(None) == (15, 16, 17, 22)
    assert parse_class_ids("15, 16") == (15, 16)
    for bad in ("bird", "15,-1", ","):
        with pytest.raises(ValueError):
            parse_class_ids(bad)


def test_config_defaults_to_bird_cat_dog_bear_and_motion_capture_off():
    cfg = Config()
    assert cfg.animal_class_ids == (15, 16, 17, 22)
    assert cfg.camera_motion_capture is False


# ── One visit per group ───────────────────────────────────────────────────────


def test_a_camping_squirrel_does_not_hide_a_bird_that_lands():
    clock = FakeClock()
    # The squirrel sits there for the whole run. A bird lands 10 s in.
    squirrel_only = [[SQUIRREL_AS_CAT]] * 50
    with_bird = [[SQUIRREL_AS_CAT, BIRD]] * 50
    trigger = _trigger(ScriptedDetector(*squirrel_only, *with_bird), clock=clock)

    events = asyncio.run(_ticks(trigger, clock, 100))

    assert [(e.class_id, e.trigger) for e in events] == [
        (CAT_CLASS_ID, "detector"),
        (BIRD_CLASS_ID, "detector"),
    ]
    assert events[1].box is not None


def test_a_camping_squirrel_is_one_visit():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([SQUIRREL_AS_CAT]), clock=clock)

    events = asyncio.run(_ticks(trigger, clock, 300))  # a minute

    assert len(events) == 1


def test_a_bird_and_a_squirrel_in_one_frame_fire_two_events():
    trigger = _trigger(ScriptedDetector([SQUIRREL_AS_CAT, BIRD]))

    asyncio.run(trigger.step())
    asyncio.run(trigger.step())

    assert sorted(e.class_id for e in _events(trigger)) == [BIRD_CLASS_ID, CAT_CLASS_ID]


def test_a_bird_still_fires_after_the_gap():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([BIRD], *[[]] * 100, [BIRD]), clock=clock, gap=15)

    events = asyncio.run(_ticks(trigger, clock, 103))

    assert len(events) == 2


# ── The motion fallback ───────────────────────────────────────────────────────


def test_motion_with_no_detection_fires_nothing_by_default():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([]), clock=clock)

    assert asyncio.run(_ticks(trigger, clock, 100)) == []


def test_motion_capture_fires_once_after_the_motion_lasts():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([]), clock=clock, motion_capture=True)

    early = asyncio.run(_ticks(trigger, clock, 14))  # 2.8 s
    later = asyncio.run(_ticks(trigger, clock, 40))  # to 10.8 s, inside the gap

    assert early == []
    [event] = later
    assert (event.trigger, event.class_id, event.box) == ("motion", None, None)


def test_motion_capture_repeats_only_after_the_gap():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([]), clock=clock, motion_capture=True, gap=15)

    times = []
    for _ in range(200):  # 40 s of wind
        asyncio.run(trigger.step())
        times.extend(clock.now for _ in _events(trigger))
        clock.now += 0.2

    # At about 3, 18 and 33 s: once per gap, never faster.
    assert len(times) == 3
    assert all(b - a >= 15 for a, b in zip(times, times[1:]))


def test_motion_capture_waits_while_a_visit_is_open():
    clock = FakeClock()
    # A bird at the start opens a visit. Then the detector sees nothing.
    trigger = _trigger(ScriptedDetector([BIRD], []), clock=clock, motion_capture=True, gap=15)

    events = asyncio.run(_ticks(trigger, clock, 60))  # 12 s, all inside the gap

    assert [e.trigger for e in events] == ["detector"]


def test_a_still_tick_does_not_break_a_run_of_motion():
    clock = FakeClock()
    # Two moving ticks, then one still one, repeated. A feeding squirrel.
    base = np.full((24, 32), 100, np.uint8)
    moved = np.full((24, 32), 220, np.uint8)
    grays = [base, moved, base, base] * 50
    trigger = _trigger(ScriptedDetector([]), clock=clock, motion_capture=True, grays=grays)

    events = asyncio.run(_ticks(trigger, clock, 40))

    assert [e.trigger for e in events] == ["motion"]


# ── The tick age the feed alerts read ─────────────────────────────────────────


def test_tick_age_counts_analysed_frames_with_motion_capture_on():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([]), clock=clock, motion_capture=True)

    asyncio.run(_ticks(trigger, clock, 20))
    assert trigger.tick_age() == pytest.approx(0.2)

    # The camera stops streaming. No frame, so no tick, whatever motion did.
    trigger._camera.grays = []
    clock.now += 600
    asyncio.run(trigger.step())
    assert trigger.tick_age() == pytest.approx(600.2)


def test_a_motion_capture_tick_is_the_frame_it_analysed():
    clock = FakeClock()
    trigger = _trigger(ScriptedDetector([]), clock=clock, motion_capture=True)

    events = asyncio.run(_ticks(trigger, clock, 20))

    assert [e.trigger for e in events] == ["motion"]
    assert trigger.tick_age() == pytest.approx(0.2)


# ── The pipeline: keep a motion capture only if Tier 2 names it ──────────────


class _Tier2(ClassifierBase):
    def __init__(self, confidence: float | None, animal: AnimalAnswer | None = None):
        self.confidence = confidence
        self.animal = animal
        self.calls = 0

    @property
    def tier_name(self) -> str:
        return "gpu"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        self.calls += 1
        if self.confidence is None:
            return None
        return ClassificationResult("House Finch", "Haemorhous mexicanus", self.confidence,
                                    self.tier_name, animal=self.animal)


class _Tier1(_Tier2):
    @property
    def tier_name(self) -> str:
        return "local"


class _FileCamera:
    async def capture(self, output_path: Path) -> Path:
        output_path.write_bytes(b"\xff\xd8 not really a jpeg")
        return output_path


class _Client:
    def __init__(self, outcome=UploadOutcome.OK):
        self.outcome = outcome
        self.posts: list[dict] = []

    async def post_sighting(self, **kwargs):
        self.posts.append(kwargs)
        return self.outcome


SQUIRREL = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.8)


def _pipeline(tmp_path, tier2, outcome=UploadOutcome.OK):
    pipeline = Pipeline(
        Config(cache_dir=str(tmp_path / "cache"), device_token="t", tier2_animal_threshold=0.3),
        camera=_FileCamera(),
    )
    pipeline._cache.setup()
    pipeline._tier2 = tier2
    pipeline._tier1 = _Tier1(0.99)
    client = _Client(outcome)
    pipeline._client = client
    return pipeline, client


async def _motion_visit(pipeline):
    from dataclasses import replace

    capture = replace(await pipeline._capture(), trigger="motion")
    await pipeline._process(capture)
    return capture


def test_a_motion_capture_tier2_names_as_an_animal_uploads(tmp_path):
    pipeline, client = _pipeline(tmp_path, _Tier2(0.02, SQUIRREL))

    asyncio.run(_motion_visit(pipeline))

    [post] = client.posts
    assert (post["common_name"], post["animal_group"], post["trigger"]) == (
        "Eastern Gray Squirrel", "squirrel", "motion")
    assert pipeline._tier1.calls == 0


def test_a_motion_capture_of_a_bird_the_detector_missed_uploads(tmp_path):
    pipeline, client = _pipeline(tmp_path, _Tier2(0.75))

    asyncio.run(_motion_visit(pipeline))

    [post] = client.posts
    assert (post["common_name"], post["animal_group"], post["trigger"]) == ("House Finch", None, "motion")


def test_a_motion_capture_named_as_neither_is_dropped(tmp_path):
    weak = AnimalAnswer("Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.1)
    pipeline, client = _pipeline(tmp_path, _Tier2(0.2, weak))

    capture = asyncio.run(_motion_visit(pipeline))

    assert client.posts == []
    assert pipeline._cache.get_pending() == []
    assert not capture.image_path.exists()
    assert pipeline._tier1.calls == 0, "Tier 1 would name a bird in a swinging feeder"


def test_a_motion_capture_with_tier2_down_is_dropped(tmp_path):
    pipeline, client = _pipeline(tmp_path, _Tier2(None))

    capture = asyncio.run(_motion_visit(pipeline))

    assert client.posts == []
    assert pipeline._cache.get_pending() == []
    assert not capture.image_path.exists()
    assert pipeline._tier1.calls == 0


def test_a_detector_capture_with_tier2_down_still_uploads_as_before(tmp_path):
    pipeline, client = _pipeline(tmp_path, _Tier2(None))

    asyncio.run(pipeline._process(asyncio.run(pipeline._capture())))

    [post] = client.posts
    assert post["trigger"] == "detector"
    assert post["tier_used"] == "local"


def test_a_queued_motion_capture_keeps_its_trigger(tmp_path):
    pipeline, client = _pipeline(tmp_path, _Tier2(0.02, SQUIRREL), outcome=UploadOutcome.RETRY)

    asyncio.run(_motion_visit(pipeline))

    [queued] = pipeline._cache.get_pending()
    assert (queued.trigger, queued.animal_group) == ("motion", "squirrel")


def test_a_full_classify_queue_drops_a_motion_capture(tmp_path):
    from dataclasses import replace

    pipeline, _ = _pipeline(tmp_path, _Tier2(0.9))
    pipeline._work = asyncio.Queue(1)
    pipeline._work.put_nowait(object())

    capture = replace(asyncio.run(pipeline._capture()), trigger="motion")
    pipeline._submit(capture)

    assert pipeline._cache.get_pending() == []
    assert not capture.image_path.exists()
