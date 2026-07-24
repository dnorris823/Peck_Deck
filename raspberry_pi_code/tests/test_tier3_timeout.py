"""Tier 3 timeout behaviour.

An unreachable backend is routine at the feeder. It must (a) give up before the
trigger debounce expires, so the Pi isn't still classifying when the next bird
lands, and (b) degrade to None quietly rather than raising or logging a trace.
"""
import asyncio
import logging
from pathlib import Path

from raspberry_pi_code.classification.tier3_cloud import CloudClassifier
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline


def test_pipeline_passes_the_configured_timeout_to_tier3(tmp_path):
    # Regression: Pipeline used to construct CloudClassifier with no timeout,
    # silently taking the 60s default regardless of config.
    cfg = Config(
        cache_dir=str(tmp_path / "cache"),
        tier3_request_timeout=7,
        device_token="t",
    )
    pipeline = Pipeline(cfg)

    assert pipeline._tier3._timeout.total == 7


def test_tier3_timeout_stays_under_the_trigger_debounce():
    cfg = Config()

    assert cfg.tier3_request_timeout < cfg.debounce_seconds, (
        "a stalled Tier 3 must not outlast the debounce window, or the pipeline "
        "is still busy when the next trigger fires"
    )


def test_timeout_returns_none_without_logging_a_traceback(tmp_path, caplog):
    image = tmp_path / "capture.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0stub")

    clf = CloudClassifier("http://127.0.0.1:9", "token", timeout_seconds=1)

    # Simulate the aiohttp total-timeout path.
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def post(self, *_, **__):
            raise asyncio.TimeoutError

    import raspberry_pi_code.classification.tier3_cloud as tier3

    original = tier3.aiohttp.ClientSession
    tier3.aiohttp.ClientSession = lambda *a, **k: _Session()
    try:
        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(clf.classify(image))
    finally:
        tier3.aiohttp.ClientSession = original

    assert result is None
    assert not any(rec.exc_info for rec in caplog.records), (
        "timeout is expected when the backend is offline — no stack trace"
    )
    assert any("timed out" in rec.message.lower() for rec in caplog.records)


def test_unreachable_backend_returns_none(tmp_path):
    image = tmp_path / "capture.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0stub")

    # Port 9 (discard) refuses fast — exercises the ClientError branch.
    clf = CloudClassifier("http://127.0.0.1:9", "token", timeout_seconds=2)

    assert asyncio.run(clf.classify(image)) is None
