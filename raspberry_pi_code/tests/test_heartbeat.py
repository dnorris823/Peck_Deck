"""The Pi's heartbeat.

The backend calls a station offline when it has not heard from it in a while.
A quiet feeder uploads nothing, so without a heartbeat a healthy Pi read
"offline" between visits. See issue 84.
"""
import asyncio
import logging

from aiohttp import web
from aiohttp.test_utils import TestServer

from raspberry_pi_code import main as pi_main
from raspberry_pi_code.api_client import BackendClient, UploadOutcome
from raspberry_pi_code.config import Config


async def _with_backend(status, body):
    """Run `body(client, seen)` against a local backend answering `status`."""
    seen = []

    async def heartbeat(request):
        seen.append((request.path, request.headers.get("Authorization")))
        return web.json_response({}, status=status)

    app = web.Application()
    app.router.add_post("/devices/me/heartbeat", heartbeat)
    async with TestServer(app) as server:
        client = BackendClient(str(server.make_url("")), "dev-token", connect_timeout=2)
        return await body(client, seen)


def test_heartbeat_posts_with_the_device_token():
    async def body(client, seen):
        outcome = await client.heartbeat()
        return outcome, seen

    outcome, seen = asyncio.run(_with_backend(200, body))
    assert outcome is UploadOutcome.OK
    assert seen == [("/devices/me/heartbeat", "Bearer dev-token")]


def test_refused_token_is_unauthorized_not_retry():
    async def body(client, _seen):
        return await client.heartbeat()

    assert asyncio.run(_with_backend(401, body)) is UploadOutcome.UNAUTHORIZED


def test_unreachable_backend_is_retry_without_a_traceback(caplog):
    # Port 9 (discard) refuses fast.
    client = BackendClient("http://127.0.0.1:9", "t", connect_timeout=2)
    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(client.heartbeat()) is UploadOutcome.RETRY
    assert not any(rec.exc_info for rec in caplog.records)


class _FakeClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    async def heartbeat(self):
        self.calls += 1
        item = self._outcomes.pop(0) if self._outcomes else UploadOutcome.OK
        if isinstance(item, Exception):
            raise item
        return item


async def _run_loop(client, ticks):
    task = asyncio.create_task(pi_main._heartbeat_loop(client, 0))
    while client.calls < ticks:
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_loop_survives_failures_and_logs_each_change_once(caplog):
    client = _FakeClient([
        UploadOutcome.RETRY, UploadOutcome.RETRY, RuntimeError("boom"),
        UploadOutcome.OK, UploadOutcome.OK,
    ])
    with caplog.at_level(logging.INFO, logger=pi_main.__name__):
        asyncio.run(_run_loop(client, 5))

    assert client.calls >= 5, "a failed beat must not stop the loop"
    failed = [r for r in caplog.records if "Heartbeat failed" in r.message]
    recovered = [r for r in caplog.records if "again" in r.message]
    assert len(failed) == 1, "a long outage is one warning, not one per beat"
    assert len(recovered) == 1


def test_interval_stays_under_the_backend_warn_cutoff():
    # The backend marks a station "warn" after 5 silent minutes.
    assert Config().heartbeat_interval_seconds < 5 * 60
