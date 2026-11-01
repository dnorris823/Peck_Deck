"""What the Pi reports about its backlog and itself in each heartbeat.

The offline queue used to be invisible. A Pi that was online but could not
upload looked healthy while its backlog grew, and a dropped sighting showed
only in a log line. See issue 185.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from raspberry_pi_code.api_client import UploadOutcome
from raspberry_pi_code.tests.test_offline_queue import (
    _add_image,
    _cache,
    _pipeline_with,
    _queued,
)
from raspberry_pi_code.vitals import cpu_temp_c, disk_free_bytes, read_vitals


def test_empty_queue_reports_zero_and_no_age(tmp_path):
    assert _cache(tmp_path).backlog() == (0, None)


def test_backlog_counts_the_queue_and_ages_the_oldest(tmp_path):
    cache = _cache(tmp_path)
    now = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
    for i, hours_ago in enumerate([3, 1, 2]):
        sighting = _queued(f"q{i}", _add_image(cache, f"q{i}", mtime=1000 + i))
        sighting.timestamp = (now - timedelta(hours=hours_ago)).isoformat()
        cache.enqueue(sighting)

    assert cache.backlog(now) == (3, 3 * 3600)


def test_a_bad_timestamp_still_counts_the_queue(tmp_path):
    cache = _cache(tmp_path)
    sighting = _queued("bad", _add_image(cache, "bad", mtime=1000))
    sighting.timestamp = "not a time"
    cache.enqueue(sighting)
    assert cache.backlog() == (1, None)


def test_a_full_queue_counts_each_sighting_it_pushes_out(tmp_path):
    cache = _cache(tmp_path, max_images=100, max_queued=2)
    for i in range(5):
        cache.enqueue(_queued(f"s{i}", _add_image(cache, f"s{i}", mtime=1000 + i)))
    assert cache.dropped == 3


def test_a_rejected_queued_sighting_counts_as_dropped(tmp_path):
    pipeline, _client = _pipeline_with(tmp_path, UploadOutcome.REJECTED)
    pipeline._cache.enqueue(_queued("e1", _add_image(pipeline._cache, "e1", mtime=1000)))

    asyncio.run(pipeline.sync_offline_queue())

    assert pipeline.backlog() == {
        "queued_sightings": 0, "oldest_queued_age_seconds": None, "dropped_since_boot": 1,
    }


def test_a_queued_sighting_with_no_image_counts_as_dropped(tmp_path):
    pipeline, client = _pipeline_with(tmp_path, UploadOutcome.OK)
    path = _add_image(pipeline._cache, "gone", mtime=1000)
    pipeline._cache.enqueue(_queued("gone", path))
    path.unlink()

    asyncio.run(pipeline.sync_offline_queue())

    assert client.calls == 0
    assert pipeline.backlog()["dropped_since_boot"] == 1


def test_an_upload_is_not_a_drop(tmp_path):
    pipeline, _client = _pipeline_with(tmp_path, UploadOutcome.OK)
    pipeline._cache.enqueue(_queued("ok", _add_image(pipeline._cache, "ok", mtime=1000)))

    asyncio.run(pipeline.sync_offline_queue())

    assert pipeline.backlog()["dropped_since_boot"] == 0


def test_a_retry_keeps_the_sighting_in_the_backlog(tmp_path):
    # The backend is down. The queue is what the card must show.
    pipeline, _client = _pipeline_with(tmp_path, UploadOutcome.RETRY)
    pipeline._cache.enqueue(_queued("wait", _add_image(pipeline._cache, "wait", mtime=1000)))

    asyncio.run(pipeline.sync_offline_queue())

    report = pipeline.backlog()
    assert report["queued_sightings"] == 1
    assert report["oldest_queued_age_seconds"] > 0
    assert report["dropped_since_boot"] == 0


def test_cpu_temp_reads_millidegrees(tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("52312\n")
    assert cpu_temp_c(zone) == 52.3


def test_cpu_temp_is_none_off_a_pi(tmp_path):
    assert cpu_temp_c(tmp_path / "missing") is None
    garbled = tmp_path / "garbled"
    garbled.write_text("hot")
    assert cpu_temp_c(garbled) is None


def test_disk_free_reads_the_cache_file_system(tmp_path):
    assert disk_free_bytes(str(tmp_path)) > 0
    assert disk_free_bytes(str(tmp_path / "missing")) is None


def test_read_vitals_returns_heartbeat_fields(tmp_path):
    assert set(read_vitals(str(tmp_path))) == {"disk_free_bytes", "cpu_temp_c"}
