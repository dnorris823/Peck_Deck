"""The Pi's heartbeat.

The backend calls a station offline when it has not heard from it in a while.
A quiet feeder uploads nothing, so without a heartbeat a healthy Pi read
"offline" between visits. See issue 84.
"""
import asyncio
import logging

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from raspberry_pi_code import main as pi_main
from raspberry_pi_code.api_client import BackendClient, UploadOutcome
from raspberry_pi_code.config import Config, parse_power_source


async def _with_backend(status, body, bodies=None):
    """Run `body(client, seen)` against a local backend answering `status`.

    Each JSON body the backend receives goes into `bodies`, when given.
    """
    seen = []

    async def heartbeat(request):
        seen.append((request.path, request.headers.get("Authorization")))
        if bodies is not None:
            bodies.append(await request.json())
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


def test_heartbeat_sends_power_source_and_signal():
    bodies = []

    async def body(client, _seen):
        await client.heartbeat(power_source="mains", signal="weak")
        await client.heartbeat()

    asyncio.run(_with_backend(200, body, bodies))
    assert bodies[0] == {"power_source": "mains", "signal": "weak"}
    # Left out, so the backend keeps what it stored.
    assert bodies[1] == {}


def test_heartbeat_sends_a_zero_trigger_age():
    # 0.0 is falsy, and it is the freshest tick there is.
    bodies = []

    async def body(client, _seen):
        await client.heartbeat(trigger_age_seconds=0.0)

    asyncio.run(_with_backend(200, body, bodies))
    assert bodies[0] == {"trigger_age_seconds": 0.0}


def test_heartbeat_sends_the_backlog_and_vitals_with_zeros_kept():
    # Zero queued and zero dropped are real readings, not missing ones.
    bodies = []

    async def body(client, _seen):
        await client.heartbeat(
            trigger_age_seconds=1.0, queued_sightings=0, oldest_queued_age_seconds=None,
            dropped_since_boot=0, disk_free_bytes=12_000_000_000, cpu_temp_c=51.2,
        )
        await client.heartbeat(queued_sightings=14, oldest_queued_age_seconds=10800.04)

    asyncio.run(_with_backend(200, body, bodies))
    assert bodies[0] == {
        "trigger_age_seconds": 1.0, "queued_sightings": 0, "dropped_since_boot": 0,
        "disk_free_bytes": 12_000_000_000, "cpu_temp_c": 51.2,
    }
    assert bodies[1] == {"queued_sightings": 14, "oldest_queued_age_seconds": 10800.0}


def test_power_source_defaults_to_mains():
    assert parse_power_source(None) == "mains"
    assert parse_power_source("") == "mains"
    assert parse_power_source(" Battery ") == "battery"


def test_unknown_power_source_refuses_to_start():
    with pytest.raises(ValueError, match="POWER_SOURCE"):
        parse_power_source("solar")


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

    async def heartbeat(self, live_url=None, power_source=None, signal=None,
                        trigger_age_seconds=None, **health):
        self.calls += 1
        self.last = {"power_source": power_source, "signal": signal,
                     "trigger_age_seconds": trigger_age_seconds}
        self.health = health
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


def test_loop_reports_power_source_and_signal_each_beat():
    client = _FakeClient([])

    async def run():
        task = asyncio.create_task(pi_main._heartbeat_loop(
            client, 0, power_source="mains", signal=lambda: "good",
            trigger_age=lambda: 1.5))
        while client.calls < 2:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert client.last == {"power_source": "mains", "signal": "good",
                           "trigger_age_seconds": 1.5}


def test_loop_reports_the_backlog_and_vitals_each_beat():
    client = _FakeClient([])
    queue = {"queued_sightings": 2, "oldest_queued_age_seconds": 30.0, "dropped_since_boot": 0}

    async def run():
        task = asyncio.create_task(pi_main._heartbeat_loop(
            client, 0, trigger_age=lambda: 0.5, backlog=lambda: queue,
            vitals=lambda: {"disk_free_bytes": 5, "cpu_temp_c": 40.0}))
        while client.calls < 2:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    # The trigger tick still goes out beside them. The feed check needs it.
    assert client.last["trigger_age_seconds"] == 0.5
    assert client.health == {**queue, "disk_free_bytes": 5, "cpu_temp_c": 40.0}


def test_interval_stays_under_the_backend_warn_cutoff():
    # The backend marks a station "warn" after 5 silent minutes.
    assert Config().heartbeat_interval_seconds < 5 * 60
