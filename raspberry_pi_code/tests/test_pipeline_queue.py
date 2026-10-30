"""A slow Tier 2 must not cost the next visit its photo.

In the desk test on 2026-10-28, Tier 2 was unreachable. The first visit held the
pipeline lock for 42 s across capture, classify and upload, and a second visit
41 s later was dropped without a capture. The lock now covers the camera only,
and ``run_classifier`` drains the captures one at a time.
"""
import asyncio
import logging
from pathlib import Path

from raspberry_pi_code.api_client import UploadOutcome
from raspberry_pi_code.classification.base import ClassificationResult, ClassifierBase
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline


class _FileCamera:
    """Writes a few bytes where the pipeline asks, like a real capture."""

    def __init__(self):
        self.captured: list[Path] = []

    async def capture(self, output_path: Path) -> Path:
        output_path.write_bytes(b"\xff\xd8 not really a jpeg")
        self.captured.append(output_path)
        return output_path


class _SlowTier2(ClassifierBase):
    """Answers only when the test releases it. Records how many calls overlap."""

    def __init__(self):
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.active = 0
        self.max_active = 0
        self.seen: list[Path] = []

    @property
    def tier_name(self) -> str:
        return "gpu"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.seen.append(image_path)
        self.started.set()
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return ClassificationResult(
            common_name="Northern Cardinal",
            scientific_name="Cardinalis cardinalis",
            confidence=0.95,
            tier_used="gpu",
        )


class _RecordingClient:
    def __init__(self):
        self.posts: list[dict] = []

    async def post_sighting(self, **kwargs) -> UploadOutcome:
        self.posts.append(kwargs)
        return UploadOutcome.OK


def _pipeline(tmp_path, **overrides) -> tuple[Pipeline, _FileCamera, _SlowTier2, _RecordingClient]:
    camera = _FileCamera()
    cfg = Config(cache_dir=str(tmp_path / "cache"), device_token="t", **overrides)
    pipeline = Pipeline(cfg, camera=camera)
    pipeline._cache.setup()
    tier2 = _SlowTier2()
    pipeline._classifiers_for_preference = lambda: [tier2]
    client = _RecordingClient()
    pipeline._client = client
    return pipeline, camera, tier2, client


async def _visit(pipeline: Pipeline) -> None:
    """One trigger. A capture that waits on Tier 2 fails here instead of hanging."""
    await asyncio.wait_for(pipeline.handle_trigger(), 1)


def test_second_visit_gets_its_own_capture_while_tier2_is_slow(tmp_path):
    pipeline, camera, tier2, client = _pipeline(tmp_path)

    async def run():
        worker = asyncio.create_task(pipeline.run_classifier())
        try:
            await _visit(pipeline)
            await asyncio.wait_for(tier2.started.wait(), 1)

            # Tier 2 is still thinking about the first visit. The second one
            # must get its photo now, not after Tier 2 answers or times out.
            await _visit(pipeline)
            assert len(camera.captured) == 2

            tier2.release.set()
            await asyncio.wait_for(pipeline._work.join(), 1)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(run())

    assert tier2.seen == camera.captured, "classified in visit order"
    assert tier2.max_active == 1, "Tier 2 must not be hit in parallel"
    assert [p["image_path"] for p in client.posts] == camera.captured
    assert pipeline._cache.get_pending() == []


def test_full_queue_warns_and_keeps_the_photo(tmp_path, caplog):
    pipeline, camera, tier2, client = _pipeline(tmp_path, classify_queue_size=1)

    async def run():
        worker = asyncio.create_task(pipeline.run_classifier())
        try:
            await _visit(pipeline)  # under classification
            await asyncio.wait_for(tier2.started.wait(), 1)
            await _visit(pipeline)  # fills the queue
            with caplog.at_level(logging.WARNING, logger="raspberry_pi_code.pipeline"):
                await _visit(pipeline)  # no room
            assert len(camera.captured) == 3

            tier2.release.set()
            await asyncio.wait_for(pipeline._work.join(), 1)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(run())

    assert any("Classify queue is full" in r.getMessage() for r in caplog.records)
    # The overflow visit waits in the offline queue for the sync loop.
    pending = pipeline._cache.get_pending()
    assert [Path(s.image_path) for s in pending] == [camera.captured[2]]
    assert pending[0].common_name == "Unknown"
    assert pending[0].tier_used == "none"
    # No tier saw it, and the trace says so.
    assert pending[0].tier_trace == [
        {"tier": "gpu", "outcome": "not_run", "confidence": None, "threshold": 0.60}
    ]
    assert camera.captured[2].exists()
    # The other two still went through the worker.
    assert [p["image_path"] for p in client.posts] == camera.captured[:2]


def test_waiting_captures_are_not_evicted(tmp_path):
    """The cache limit must not delete a photo before it is classified."""
    pipeline, camera, tier2, client = _pipeline(tmp_path, max_cache_images=1)

    async def run():
        worker = asyncio.create_task(pipeline.run_classifier())
        try:
            for _ in range(3):
                await _visit(pipeline)
            await asyncio.wait_for(tier2.started.wait(), 1)
            assert all(p.exists() for p in camera.captured), "a waiting capture was evicted"

            tier2.release.set()
            await asyncio.wait_for(pipeline._work.join(), 1)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(run())

    assert len(client.posts) == 3


def test_worker_survives_a_failed_capture(tmp_path):
    pipeline, camera, tier2, client = _pipeline(tmp_path)
    tier2.release.set()
    real_process = pipeline._process
    calls = 0

    async def flaky_process(capture):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        await real_process(capture)

    pipeline._process = flaky_process

    async def run():
        worker = asyncio.create_task(pipeline.run_classifier())
        try:
            await _visit(pipeline)
            await _visit(pipeline)
            await asyncio.wait_for(pipeline._work.join(), 1)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(run())

    assert [p["image_path"] for p in client.posts] == [camera.captured[1]]
    assert pipeline._in_flight == set()
