"""Offline-queue durability and upload-failure classification.

Both behaviours here were found during the Phase 4 bring-up run on real
hardware, when a stale ``DEVICE_TOKEN`` made every upload fail:

* the Pi logged *"Backend unreachable"* for an HTTP 401 the backend had
  answered instantly, and
* the rolling image cache happily deleted images that the offline queue was
  still pointing at, so the backlog destroyed itself as it grew.
"""
import asyncio
import json
from pathlib import Path

import pytest

from raspberry_pi_code.api_client import UploadOutcome, _classify_status
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline
from raspberry_pi_code.storage.local_cache import LocalCache, QueuedSighting


# ── Status classification ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status, expected",
    [
        (200, UploadOutcome.OK),
        (201, UploadOutcome.OK),
        (401, UploadOutcome.UNAUTHORIZED),
        (403, UploadOutcome.UNAUTHORIZED),
        (400, UploadOutcome.REJECTED),
        (422, UploadOutcome.REJECTED),
        (413, UploadOutcome.REJECTED),
        (429, UploadOutcome.RETRY),
        (500, UploadOutcome.RETRY),
        (503, UploadOutcome.RETRY),
    ],
)
def test_status_classification(status, expected):
    assert _classify_status(status) is expected


def test_only_ok_is_truthy():
    """Existing ``if ok:`` call sites (the simulator) must keep working."""
    assert UploadOutcome.OK
    assert not UploadOutcome.RETRY
    assert not UploadOutcome.UNAUTHORIZED
    assert not UploadOutcome.REJECTED


# ── Cache eviction vs. the queue ─────────────────────────────────────────────

def _cache(tmp_path, max_images=3, max_queued=200) -> LocalCache:
    cache = LocalCache(str(tmp_path / "cache"), max_images, max_queued)
    cache.setup()
    return cache


def _add_image(cache: LocalCache, event_id: str, mtime: float) -> Path:
    path = cache.image_path_for(event_id)
    path.write_bytes(b"\xff\xd8\xff\xd9")
    import os
    os.utime(path, (mtime, mtime))
    return path


def _queued(event_id: str, path: Path) -> QueuedSighting:
    return QueuedSighting(
        id=event_id,
        timestamp="2026-07-25T11:00:00+00:00",
        image_path=str(path),
        common_name="Downy Woodpecker",
        scientific_name="Dryobates pubescens",
        confidence=0.42,
        tier_used="local",
    )


def test_eviction_never_deletes_a_queued_image(tmp_path):
    """The regression: a backlog longer than the cache limit ate itself."""
    cache = _cache(tmp_path, max_images=3)

    # Five captures, all queued (as happens when the backend is unreachable).
    paths = {}
    for i in range(5):
        eid = f"queued{i}"
        paths[eid] = _add_image(cache, eid, mtime=1000 + i)
        cache.enqueue(_queued(eid, paths[eid]))

    cache.evict_if_needed()

    for eid, path in paths.items():
        assert path.exists(), f"{eid} was evicted while still queued for upload"
    assert len(cache.get_pending()) == 5


def test_eviction_still_trims_unqueued_images(tmp_path):
    """Protecting the queue must not disable the rolling cache entirely."""
    cache = _cache(tmp_path, max_images=3)
    loose = [_add_image(cache, f"loose{i}", mtime=1000 + i) for i in range(6)]

    cache.evict_if_needed()

    remaining = sorted(p.name for p in cache._images.glob("*.jpg"))
    assert len(remaining) == 3
    # Oldest three go, newest three stay.
    assert not any(p.exists() for p in loose[:3])
    assert all(p.exists() for p in loose[3:])


def test_eviction_prefers_unqueued_images_over_queued_ones(tmp_path):
    cache = _cache(tmp_path, max_images=2)

    old_queued = _add_image(cache, "queued", mtime=1000)
    cache.enqueue(_queued("queued", old_queued))
    newer_loose = [_add_image(cache, f"loose{i}", mtime=2000 + i) for i in range(3)]

    cache.evict_if_needed()

    # The queued image is the oldest, but it survives; loose ones absorb the cut.
    assert old_queued.exists()
    assert sum(p.exists() for p in newer_loose) == 1


def test_in_flight_capture_survives_a_full_queue(tmp_path):
    """Regression from the 2026-07-25 bring-up run.

    Once every queued image is protected, the capture currently being
    classified is the only thing left to evict — and it was duly deleted while
    Tier 1 was reading it, which showed up on the Pi as "Tier 'local' failed"
    followed by the sighting being discarded.
    """
    cache = _cache(tmp_path, max_images=2)
    for i in range(2):
        path = _add_image(cache, f"queued{i}", mtime=1000 + i)
        cache.enqueue(_queued(f"queued{i}", path))

    in_flight = _add_image(cache, "inflight", mtime=3000)
    cache.evict_if_needed(protect=in_flight)

    assert in_flight.exists(), "the capture being classified was evicted mid-flight"
    assert len(cache.get_pending()) == 2


def test_queue_is_bounded_and_drops_oldest_first(tmp_path):
    cache = _cache(tmp_path, max_images=100, max_queued=3)

    paths = {}
    for i in range(5):
        eid = f"s{i}"
        paths[eid] = _add_image(cache, eid, mtime=1000 + i)
        cache.enqueue(_queued(eid, paths[eid]))

    pending = cache.get_pending()
    assert [s.id for s in pending] == ["s2", "s3", "s4"]
    # Dropped entries take their images with them — no orphans on the SD card.
    assert not paths["s0"].exists()
    assert not paths["s1"].exists()
    assert paths["s4"].exists()


def test_queue_file_stays_valid_json(tmp_path):
    cache = _cache(tmp_path, max_queued=2)
    for i in range(4):
        path = _add_image(cache, f"j{i}", mtime=1000 + i)
        cache.enqueue(_queued(f"j{i}", path))

    raw = json.loads((tmp_path / "cache" / "queue.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list) and len(raw) == 2


# ── Pipeline reaction to each outcome ────────────────────────────────────────

class _StubClient:
    def __init__(self, outcome: UploadOutcome):
        self.outcome = outcome
        self.calls = 0

    async def post_sighting(self, **kwargs) -> UploadOutcome:
        self.calls += 1
        return self.outcome

    async def is_reachable(self) -> bool:
        return True


def _pipeline_with(tmp_path, outcome: UploadOutcome) -> tuple[Pipeline, _StubClient]:
    cfg = Config(cache_dir=str(tmp_path / "cache"), device_token="t")
    pipeline = Pipeline(cfg)
    client = _StubClient(outcome)
    pipeline._client = client
    pipeline._cache.setup()
    return pipeline, client


@pytest.mark.parametrize(
    "outcome, should_queue",
    [
        (UploadOutcome.RETRY, True),
        (UploadOutcome.UNAUTHORIZED, True),   # recoverable: fix the token, backlog uploads
        (UploadOutcome.REJECTED, False),      # unfixable: queueing it poisons the queue
    ],
)
def test_sync_pass_handles_each_outcome(tmp_path, outcome, should_queue):
    """A queued sighting is kept, dropped, or abandoned per outcome."""
    pipeline, client = _pipeline_with(tmp_path, outcome)
    path = _add_image(pipeline._cache, "e1", mtime=1000)
    pipeline._cache.enqueue(_queued("e1", path))

    asyncio.run(pipeline.sync_offline_queue())

    assert client.calls == 1
    assert bool(pipeline._cache.get_pending()) is should_queue


def test_unauthorized_abandons_the_rest_of_the_sync_pass(tmp_path):
    """One 401 means every remaining item would 401 too — don't hammer them."""
    pipeline, client = _pipeline_with(tmp_path, UploadOutcome.UNAUTHORIZED)
    for i in range(4):
        path = _add_image(pipeline._cache, f"e{i}", mtime=1000 + i)
        pipeline._cache.enqueue(_queued(f"e{i}", path))

    asyncio.run(pipeline.sync_offline_queue())

    assert client.calls == 1, "should stop after the first rejected token"
    assert len(pipeline._cache.get_pending()) == 4, "backlog must survive intact"
