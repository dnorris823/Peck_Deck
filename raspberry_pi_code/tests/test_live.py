"""Live video on demand, and the live_url the heartbeat reports.

Fakes stand in for the camera, the encoder and the demand socket. One test
uses a real Unix socket and skips where the platform has none. The Pi run
recorded in the pull request covers the hardware.
"""
import asyncio
import socket
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from raspberry_pi_code import main as pi_main
from raspberry_pi_code.api_client import BackendClient, UploadOutcome
from raspberry_pi_code.camera.pi_camera import PiCamera
from raspberry_pi_code.config import Config
from raspberry_pi_code.live.address import LiveUrl, derive_live_url, is_acceptable
from raspberry_pi_code.live.demand import LiveDemandServer


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeEncoder:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.starts = 0
        self.stops = 0

    @property
    def running(self) -> bool:
        return self.starts > self.stops

    def start(self) -> None:
        if self.fail:
            raise RuntimeError("no encoder")
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class FakeReader:
    """A demand connection. ``hang_up()`` is the helper being killed."""

    def __init__(self):
        self._closed = asyncio.Event()

    def hang_up(self) -> None:
        self._closed.set()

    async def read(self, n: int = -1) -> bytes:
        await self._closed.wait()
        return b""


class FakeWriter:
    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def _settle() -> None:
    # Encoder calls go through a worker thread. Give them time to land.
    for _ in range(50):
        await asyncio.sleep(0.01)


def _server(encoder: FakeEncoder) -> LiveDemandServer:
    return LiveDemandServer("/nonexistent/live.sock", encoder.start, encoder.stop)


# ── Demand counting ───────────────────────────────────────────────────────────


def test_first_connection_starts_and_last_close_stops():
    async def body():
        enc = FakeEncoder()
        server = _server(enc)
        reader, writer = FakeReader(), FakeWriter()
        task = asyncio.create_task(server.handle(reader, writer))
        await _settle()
        assert enc.starts == 1 and enc.running
        reader.hang_up()
        await task
        assert enc.stops == 1 and not enc.running
        assert writer.closed

    asyncio.run(body())


def test_overlapping_connections_start_the_encoder_once():
    async def body():
        enc = FakeEncoder()
        server = _server(enc)
        a, b = FakeReader(), FakeReader()
        ta = asyncio.create_task(server.handle(a, FakeWriter()))
        tb = asyncio.create_task(server.handle(b, FakeWriter()))
        await _settle()
        assert enc.starts == 1

        a.hang_up()
        await ta
        assert enc.stops == 0, "one viewer is still watching"

        b.hang_up()
        await tb
        assert enc.stops == 1

    asyncio.run(body())


def test_a_failed_start_closes_the_connection_and_logs_once(caplog):
    async def body():
        enc = FakeEncoder(fail=True)
        server = _server(enc)
        for _ in range(3):
            writer = FakeWriter()
            # The handler returns without waiting for the helper to hang up.
            await asyncio.wait_for(server.handle(FakeReader(), writer), timeout=2)
            assert writer.closed
        assert enc.stops == 0
        assert not server.encoding

    with caplog.at_level("INFO", logger="raspberry_pi_code.live.demand"):
        asyncio.run(body())
    failures = [r for r in caplog.records if "failed to start" in r.message]
    assert len(failures) == 1, "a viewer retrying must not fill the journal"


def test_a_failed_stop_does_not_escape():
    async def body():
        enc = FakeEncoder()

        def bad_stop():
            raise RuntimeError("stuck")

        server = LiveDemandServer("/nonexistent/live.sock", enc.start, bad_stop)
        reader = FakeReader()
        task = asyncio.create_task(server.handle(reader, FakeWriter()))
        await _settle()
        reader.hang_up()
        await task
        assert not server.encoding

    asyncio.run(body())


def test_a_socket_that_cannot_open_turns_live_off_without_raising(tmp_path):
    # A regular file where the socket's directory should be.
    blocker = tmp_path / "file"
    blocker.write_text("x")

    async def body():
        enc = FakeEncoder()
        async with LiveDemandServer(str(blocker / "live.sock"), enc.start, enc.stop) as server:
            assert not server.listening

    asyncio.run(body())


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets")
def test_real_socket_round_trip(tmp_path):
    path = tmp_path / "live.sock"

    async def body():
        enc = FakeEncoder()
        async with LiveDemandServer(str(path), enc.start, enc.stop) as server:
            assert server.listening
            assert (path.stat().st_mode & 0o777) == 0o600
            reader, writer = await asyncio.open_unix_connection(str(path))
            await _settle()
            assert enc.running
            writer.close()
            await _settle()
            assert enc.stops == 1
        assert not path.exists()

    asyncio.run(body())


# ── Wiring ────────────────────────────────────────────────────────────────────


def test_live_disabled_opens_no_socket_and_sends_no_url():
    config = Config(live_enabled=False)
    live = pi_main._build_live(config, PiCamera())
    assert live is None
    assert pi_main._live_url_source(config, live)() is None


def test_live_enabled_builds_a_server_on_the_configured_socket():
    config = Config(live_enabled=True, live_demand_socket="/tmp/x/live.sock")
    live = pi_main._build_live(config, PiCamera())
    assert isinstance(live, LiveDemandServer)
    assert live._path == Path("/tmp/x/live.sock")


def test_a_closed_socket_reports_no_url():
    config = Config(live_url="http://192.168.4.20:8889/feeder/whep")
    live = LiveDemandServer("/nonexistent/live.sock", lambda: None, lambda: None)
    assert not live.listening
    assert pi_main._live_url_source(config, live)() is None


# ── live_url ──────────────────────────────────────────────────────────────────


def test_derived_url_uses_the_address_on_the_route_to_the_backend():
    assert derive_live_url("http://127.0.0.1:8000") == "http://127.0.0.1:8889/feeder/whep"


def test_derivation_without_a_host_gives_none():
    assert derive_live_url("not a url") is None


def test_live_url_setting_wins_over_derivation():
    url = LiveUrl("http://192.168.4.20:8889/feeder/whep", "http://127.0.0.1:8000")
    assert url() == "http://192.168.4.20:8889/feeder/whep"


@pytest.mark.parametrize("url, ok", [
    ("http://192.168.4.20:8889/feeder/whep", True),
    ("https://10.1.2.3:8889/feeder/whep", True),
    ("http://172.16.0.9:8889/feeder/whep", True),
    ("http://100.94.143.97:8889/feeder/whep", True),
    ("http://8.8.8.8:8889/feeder/whep", False),
    ("http://127.0.0.1:8889/feeder/whep", False),
    ("http://peck-pi.local:8889/feeder/whep", False),
    ("ftp://192.168.4.20/feeder", False),
    ("garbage", False),
])
def test_only_urls_the_backend_accepts_are_sent(url, ok):
    assert is_acceptable(url) is ok


def test_a_refused_url_is_dropped_and_logged_once(caplog):
    url = LiveUrl("http://8.8.8.8:8889/feeder/whep", "http://127.0.0.1:8000")
    with caplog.at_level("WARNING"):
        assert url() is None
        assert url() is None
    assert len([r for r in caplog.records if "LIVE_URL" in r.message]) == 1


def test_heartbeat_sends_live_url_and_leaves_it_out_when_none():
    seen = []

    async def heartbeat(request):
        seen.append(await request.json())
        return web.json_response({})

    async def body():
        app = web.Application()
        app.router.add_post("/devices/me/heartbeat", heartbeat)
        async with TestServer(app) as server:
            client = BackendClient(str(server.make_url("")), "t", connect_timeout=2)
            assert await client.heartbeat(live_url="http://192.168.4.20:8889/feeder/whep") \
                is UploadOutcome.OK
            assert await client.heartbeat() is UploadOutcome.OK

    asyncio.run(body())
    assert seen == [{"live_url": "http://192.168.4.20:8889/feeder/whep"}, {}]


def test_heartbeat_loop_passes_the_url_through():
    class Client:
        def __init__(self):
            self.urls = []

        async def heartbeat(self, live_url=None, **_):
            self.urls.append(live_url)
            return UploadOutcome.OK

    async def body():
        client = Client()
        task = asyncio.create_task(
            pi_main._heartbeat_loop(client, 0, lambda: "http://10.0.0.5:8889/feeder/whep")
        )
        while len(client.urls) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        return client.urls

    assert set(asyncio.run(body())) == {"http://10.0.0.5:8889/feeder/whep"}


# ── PiCamera with a fake picamera2 ────────────────────────────────────────────


class FakePicamera2:
    """Records encoder calls. Captures block until released, like a slow still."""

    def __init__(self):
        self.encoders = []
        self.captures = 0
        self.lores_yuv = np.arange(1080 * 1280, dtype=np.uint32).astype(np.uint8).reshape(1080, 1280)

    def start_encoder(self, encoder, output, name=None):
        self.encoders.append((encoder, output, name))

    def stop_encoder(self, encoders=None):
        for enc in encoders:
            self.encoders = [e for e in self.encoders if e[0] is not enc]

    def capture_file(self, path):
        self.captures += 1
        Path(path).write_bytes(b"jpeg")

    def capture_array(self, name):
        assert name == "lores"
        return self.lores_yuv


@pytest.fixture
def fake_picamera2_modules(monkeypatch):
    class Encoder:
        def __init__(self, bitrate=None, framerate=30, iperiod=30, **_):
            self.bitrate, self.framerate, self.iperiod = bitrate, framerate, iperiod

    class Output:
        def __init__(self, url, format=None):
            self.url, self.format = url, format
            self.error_callback = None

    encoders = types.ModuleType("picamera2.encoders")
    encoders.LibavH264Encoder = Encoder
    outputs = types.ModuleType("picamera2.outputs")
    outputs.PyavOutput = Output
    monkeypatch.setitem(sys.modules, "picamera2", types.ModuleType("picamera2"))
    monkeypatch.setitem(sys.modules, "picamera2.encoders", encoders)
    monkeypatch.setitem(sys.modules, "picamera2.outputs", outputs)


def _streaming_camera() -> tuple[PiCamera, FakePicamera2]:
    camera = PiCamera(fps=30)
    fake = FakePicamera2()
    camera._cam = fake
    return camera, fake


def test_start_live_encodes_lores_to_rtsp(fake_picamera2_modules):
    camera, fake = _streaming_camera()
    camera.start_live("rtsp://127.0.0.1:8554/feeder", 2_000_000)
    [(encoder, output, name)] = fake.encoders
    assert name == "lores"
    assert (encoder.bitrate, encoder.framerate, encoder.iperiod) == (2_000_000, 30, 30)
    assert (output.url, output.format) == ("rtsp://127.0.0.1:8554/feeder", "rtsp")

    camera.start_live("rtsp://127.0.0.1:8554/feeder", 2_000_000)
    assert len(fake.encoders) == 1, "a second start must not add an encoder"
    camera.stop_live()
    assert fake.encoders == []
    camera.stop_live()


def test_start_live_without_a_camera_raises():
    with pytest.raises(RuntimeError):
        PiCamera().start_live("rtsp://127.0.0.1:8554/feeder", 2_000_000)


def test_a_capture_runs_while_the_encoder_runs(fake_picamera2_modules, tmp_path):
    async def body():
        camera, fake = _streaming_camera()
        enc_started = threading.Event()
        server = LiveDemandServer(
            "/nonexistent/live.sock",
            start=lambda: (camera.start_live("rtsp://x", 1), enc_started.set()),
            stop=camera.stop_live,
        )
        reader = FakeReader()
        task = asyncio.create_task(server.handle(reader, FakeWriter()))
        await _settle()
        assert enc_started.is_set() and server.encoding

        await camera.capture(tmp_path / "a.jpg")
        gray = await camera.grab_gray()
        assert fake.captures == 1 and gray is not None
        assert len(fake.encoders) == 1, "the capture must not stop the encoder"

        reader.hang_up()
        await task
        assert fake.encoders == []

    asyncio.run(body())


def test_encoder_start_does_not_wait_for_the_camera_lock(fake_picamera2_modules):
    async def body():
        camera, fake = _streaming_camera()
        async with camera._lock:  # a capture in progress
            await asyncio.wait_for(
                asyncio.to_thread(camera.start_live, "rtsp://x", 1), timeout=2
            )
        assert len(fake.encoders) == 1

    asyncio.run(body())


def test_grab_gray_subsamples_the_y_plane_to_320x180():
    async def body():
        camera, fake = _streaming_camera()
        gray = await camera.grab_gray()
        assert gray.shape == (180, 320)
        assert gray[1, 1] == fake.lores_yuv[4, 4]

    asyncio.run(body())
