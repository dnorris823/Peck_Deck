"""The live video address on heartbeats, the WHEP signaling relay, and HLS.

The relay tests run against a fake MediaMTX on 127.0.0.1. Loopback is not a
private address the heartbeat accepts, so those tests add it to the allowed
networks for their own duration.
"""
import base64
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_network
from types import SimpleNamespace

import pytest

from backend.config import settings
from backend.devices.controller import live_available
from backend.live import address, controller, hls, whep
from backend.live.address import check_live_url
from backend.tests.conftest import IDS
from backend.tests.test_devices import _fresh_owner

OFFER = b"v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\ns=offer\r\n"
ANSWER = b"v=0\r\no=- 2 2 IN IP4 0.0.0.0\r\ns=answer\r\n"
PLAYLIST = b'#EXTM3U\n#EXT-X-VERSION:9\n#EXT-X-PART:DURATION=0.2,URI="abc_part7.mp4"\n'
# Bigger than one relay chunk, so the body arrives in pieces.
SEGMENT = bytes(range(256)) * 1024
BASIC = "Basic " + base64.b64encode(b"viewer:s3cret").decode()


# --- The address check ---

@pytest.mark.parametrize("url", [
    "http://192.168.4.30:8889/feeder/whep",
    "http://10.0.0.7:8889/feeder/whep",
    "https://172.20.1.2:8889/feeder/whep",
    "http://100.101.102.103:8889/feeder/whep",  # Tailscale
])
def test_private_live_urls_pass(url):
    assert check_live_url(url) is None


@pytest.mark.parametrize("url", [
    "http://8.8.8.8:8889/feeder/whep",          # public
    "http://127.0.0.1:8889/feeder/whep",        # loopback is the backend itself
    "http://169.254.169.254/latest/meta-data",  # link-local metadata service
    "http://172.32.0.1:8889/feeder/whep",       # just past 172.16/12
    "http://100.128.0.1:8889/feeder/whep",      # just past 100.64/10
    "http://peck-pi.local:8889/feeder/whep",    # hostname, could resolve anywhere
    "http://[fd00::1]:8889/feeder/whep",        # IPv6 is not on the list
    "ftp://192.168.4.30/feeder/whep",
    "http://user:pw@192.168.4.30:8889/feeder/whep",
    "http://192.168.4.30:notaport/feeder/whep",
    "not a url",
    "",
])
def test_other_live_urls_fail(url):
    assert check_live_url(url) is not None


def test_live_available_needs_a_url_and_a_recent_heartbeat():
    now = datetime.now(timezone.utc)

    def dev(live_url, seen):
        return SimpleNamespace(live_url=live_url, last_seen=seen, battery=None,
                               power_source=None, signal=None)

    url = "http://10.0.0.7:8889/feeder/whep"
    assert live_available(dev(url, now))
    assert not live_available(dev(None, now))
    assert not live_available(dev(url, now - timedelta(hours=1)))


# --- The heartbeat stores, clears, and refuses live_url ---

def _new_device(client):
    headers = _fresh_owner(client)
    created = client.post("/devices", json={"name": "Live Cam"}, headers=headers).json()
    return created["id"], {"Authorization": f"Bearer {created['token']}"}, headers


def _listed(client, headers, device_id):
    return next(d for d in client.get("/devices", headers=headers).json() if d["id"] == device_id)


def test_heartbeat_stores_and_clears_live_url(client):
    device_id, device_headers, user_headers = _new_device(client)
    assert _listed(client, user_headers, device_id)["live_available"] is False

    url = "http://192.168.4.30:8889/feeder/whep"
    res = client.post("/devices/me/heartbeat", json={"live_url": url}, headers=device_headers)
    assert res.status_code == 200
    assert res.json()["live_available"] is True
    listed = _listed(client, user_headers, device_id)
    assert listed["live_available"] is True
    assert "live_url" not in listed  # the browser never learns the address

    res = client.post("/devices/me/heartbeat", json={"signal": "good"}, headers=device_headers)
    assert res.status_code == 200
    assert _listed(client, user_headers, device_id)["live_available"] is False


@pytest.mark.parametrize("url", ["http://8.8.8.8:8889/feeder/whep", "garbage"])
def test_heartbeat_refuses_public_or_malformed_live_url(client, url):
    device_id, device_headers, user_headers = _new_device(client)
    client.post("/devices/me/heartbeat",
                json={"live_url": "http://10.0.0.7:8889/feeder/whep"}, headers=device_headers)

    for path in ("/devices/me/heartbeat", f"/devices/{device_id}/heartbeat"):
        res = client.post(path, json={"live_url": url}, headers=device_headers)
        assert res.status_code == 400
    # A refused heartbeat changes nothing.
    assert _listed(client, user_headers, device_id)["live_available"] is True


# --- A fake MediaMTX ---

class FakeMediaMTX:
    """Answers WHEP and HLS like MediaMTX.

    WHEP gets 201, an SDP answer, and a session Location. HLS serves one
    playlist and one segment.
    """

    def __init__(self):
        self.requests: list[dict] = []
        self.sessions: set[str] = set()
        self.delay = 0.0
        self.offer_status = 201
        self.hls_status = 200
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                fake.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                    "body": self.rfile.read(length) if length else b"",
                })

            def _reply(self, status, body=b"", headers=None):
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self._record()
                time.sleep(fake.delay)
                if self.path != "/feeder/whep":
                    return self._reply(404)
                if fake.offer_status != 201:
                    return self._reply(fake.offer_status)
                session = str(uuid.uuid4())
                fake.sessions.add(session)
                self._reply(201, ANSWER, {
                    "Content-Type": "application/sdp",
                    "Location": f"/feeder/whep/{session}",
                })

            def do_GET(self):
                self._record()
                time.sleep(fake.delay)
                if fake.hls_status != 200:
                    return self._reply(fake.hls_status)
                path, _, query = self.path.partition("?")
                # MediaMTX's cookie check on the first playlist request.
                if path == "/feeder/index.m3u8" and "cookieCheck=1" not in query:
                    return self._reply(302, b"", {
                        "Location": "/feeder/index.m3u8?cookieCheck=1",
                        "Set-Cookie": "cookieCheck=1; HttpOnly; Secure",
                    })
                if path == "/feeder/away.m3u8":
                    return self._reply(302, b"", {"Location": "http://8.8.8.8/feeder/index.m3u8"})
                if path == "/feeder/index.m3u8":
                    return self._reply(200, PLAYLIST,
                                       {"Content-Type": "application/vnd.apple.mpegurl"})
                if path == "/feeder/abc_seg3.mp4":
                    return self._reply(200, SEGMENT, {"Content-Type": "video/mp4"})
                self._reply(404)

            def do_DELETE(self):
                self._record()
                session = self.path.rsplit("/", 1)[-1]
                if session not in fake.sessions:
                    return self._reply(404)
                fake.sessions.discard(session)
                self._reply(200)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/feeder/whep"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def mediamtx(monkeypatch):
    monkeypatch.setattr(address, "ALLOWED_NETWORKS",
                        [*address.ALLOWED_NETWORKS, ip_network("127.0.0.0/8")])
    monkeypatch.setattr(settings, "LIVE_READ_USER", "viewer")
    monkeypatch.setattr(settings, "LIVE_READ_PASSWORD", "s3cret")
    fake = FakeMediaMTX()
    # One fake answers both. HLS takes the live_url host and this port.
    monkeypatch.setattr(settings, "LIVE_HLS_PORT", fake.server.server_port)
    yield fake
    fake.close()


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    controller.clear_access_cache()
    yield
    controller.clear_access_cache()


@pytest.fixture
def streaming(client, mediamtx):
    """A fresh device whose heartbeat points at the fake MediaMTX."""
    device_id, device_headers, user_headers = _new_device(client)
    res = client.post("/devices/me/heartbeat", json={"live_url": mediamtx.url},
                      headers=device_headers)
    assert res.status_code == 200
    return SimpleNamespace(id=device_id, device_headers=device_headers,
                           user_headers=user_headers, fake=mediamtx)


def _offer(client, device_id, headers, body=OFFER, content_type="application/sdp"):
    return client.post(f"/devices/{device_id}/live/whep", content=body,
                       headers={**headers, "Content-Type": content_type})


# --- POST /devices/{id}/live/whep ---

def test_offer_returns_the_answer_and_a_session_location(client, streaming):
    res = _offer(client, streaming.id, streaming.user_headers)
    assert res.status_code == 201
    assert res.content == ANSWER
    assert res.headers["content-type"].startswith("application/sdp")

    (session,) = streaming.fake.sessions
    assert res.headers["location"] == f"/devices/{streaming.id}/live/whep/{session}"

    (sent,) = streaming.fake.requests
    assert sent["method"] == "POST"
    assert sent["body"] == OFFER
    assert sent["content_type"] == "application/sdp"
    assert sent["auth"] == BASIC


def test_offer_from_a_user_without_access_is_404(client, streaming, viewer_headers):
    # The seeded viewer is a member of Dev One only.
    assert _offer(client, streaming.id, viewer_headers).status_code == 404
    assert streaming.fake.requests == []


def test_offer_for_a_missing_device_is_404(client, owner_headers):
    assert _offer(client, 999999, owner_headers).status_code == 404


def test_offer_needs_a_user_jwt(client, streaming):
    assert _offer(client, streaming.id, {}).status_code == 401
    assert _offer(client, streaming.id, streaming.device_headers).status_code == 401
    assert streaming.fake.requests == []


def test_offer_without_live_url_is_503(client, owner_headers):
    # Seeded devices have never sent a live_url.
    res = _offer(client, IDS["dev1_id"], owner_headers)
    assert res.status_code == 503
    assert res.json()["detail"] == "feeder not streaming"


def test_offer_that_times_out_upstream_is_503(client, streaming, monkeypatch):
    monkeypatch.setattr(whep, "OFFER_TIMEOUT_SECONDS", 0.3)
    streaming.fake.delay = 1.0
    res = _offer(client, streaming.id, streaming.user_headers)
    assert res.status_code == 503
    assert res.json()["detail"] == "feeder not streaming"


def test_offer_when_mediamtx_is_down_is_503(client, streaming):
    streaming.fake.close()
    assert _offer(client, streaming.id, streaming.user_headers).status_code == 503


def test_offer_when_mediamtx_has_no_stream_is_503(client, streaming):
    streaming.fake.offer_status = 404
    res = _offer(client, streaming.id, streaming.user_headers)
    assert res.status_code == 503
    assert res.json()["detail"] == "feeder not streaming"


def test_offer_refused_upstream_is_502(client, streaming):
    streaming.fake.offer_status = 401  # the read credentials do not match
    assert _offer(client, streaming.id, streaming.user_headers).status_code == 502


def test_offer_must_be_sdp(client, streaming):
    res = _offer(client, streaming.id, streaming.user_headers,
                 body=b"{}", content_type="application/json")
    assert res.status_code == 415
    assert _offer(client, streaming.id, streaming.user_headers, body=b"").status_code == 400
    assert streaming.fake.requests == []


# --- DELETE /devices/{id}/live/whep/{session} ---

def test_hang_up_reaches_mediamtx_with_the_session_id(client, streaming):
    location = _offer(client, streaming.id, streaming.user_headers).headers["location"]
    session = location.rsplit("/", 1)[-1]

    assert client.delete(location, headers=streaming.user_headers).status_code == 204
    hang_up = streaming.fake.requests[-1]
    assert hang_up["method"] == "DELETE"
    assert hang_up["path"] == f"/feeder/whep/{session}"
    assert hang_up["auth"] == BASIC
    assert streaming.fake.sessions == set()


def test_hang_up_on_an_unknown_session_is_503(client, streaming):
    res = client.delete(f"/devices/{streaming.id}/live/whep/{uuid.uuid4()}",
                        headers=streaming.user_headers)
    assert res.status_code == 503


def test_hang_up_needs_access_and_a_user_jwt(client, streaming, viewer_headers):
    location = _offer(client, streaming.id, streaming.user_headers).headers["location"]
    assert client.delete(location, headers=viewer_headers).status_code == 404
    assert client.delete(location).status_code == 401
    assert client.delete(location, headers=streaming.device_headers).status_code == 401
    assert len(streaming.fake.sessions) == 1


def test_hang_up_refuses_a_session_id_that_is_not_one(client, streaming):
    res = client.delete(f"/devices/{streaming.id}/live/whep/a.b",
                        headers=streaming.user_headers)
    assert res.status_code == 404
    assert [r["method"] for r in streaming.fake.requests] == []


def test_no_trickle_ice(client, streaming):
    location = _offer(client, streaming.id, streaming.user_headers).headers["location"]
    res = client.patch(location, content=b"a=candidate",
                       headers={**streaming.user_headers,
                                "Content-Type": "application/trickle-ice-sdpfrag"})
    assert res.status_code == 405


# --- GET /devices/{id}/live/hls/{name} ---

def _hls(client, device_id, name, headers, query=""):
    return client.get(f"/devices/{device_id}/live/hls/{name}{query}", headers=headers)


def test_hls_relays_a_playlist_with_its_query_string(client, streaming):
    res = _hls(client, streaming.id, "index.m3u8", streaming.user_headers,
               "?cookieCheck=1&_HLS_msn=12&_HLS_part=3")
    assert res.status_code == 200
    assert res.content == PLAYLIST
    assert res.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert res.headers["cache-control"] == "no-store"

    (sent,) = streaming.fake.requests
    assert sent["method"] == "GET"
    assert sent["path"] == "/feeder/index.m3u8?cookieCheck=1&_HLS_msn=12&_HLS_part=3"
    assert sent["auth"] == BASIC


def test_hls_passes_the_cookie_check_redirect_without_the_cookie(client, streaming):
    res = client.get(f"/devices/{streaming.id}/live/hls/index.m3u8",
                     headers=streaming.user_headers, follow_redirects=False)
    assert res.status_code == 302
    # Relative, so the browser comes back through the relay.
    assert res.headers["location"] == "index.m3u8?cookieCheck=1"
    assert "set-cookie" not in res.headers


def test_hls_refuses_a_redirect_off_the_stream(client, streaming):
    res = client.get(f"/devices/{streaming.id}/live/hls/away.m3u8",
                     headers=streaming.user_headers, follow_redirects=False)
    assert res.status_code == 502


@pytest.mark.parametrize("location,expected", [
    ("/feeder/index.m3u8?cookieCheck=1", "index.m3u8?cookieCheck=1"),
    ("/feeder/video1_stream.m3u8", "video1_stream.m3u8"),
    ("http://192.168.4.104:8888/feeder/index.m3u8", None),
    ("//8.8.8.8/feeder/index.m3u8", None),
    ("/other/index.m3u8", None),
    ("/feeder/../whep", None),
    ("", None),
])
def test_relative_location(location, expected):
    assert hls.relative_location(location) == expected


def test_hls_relays_a_segment_with_its_bytes_and_type(client, streaming):
    res = _hls(client, streaming.id, "abc_seg3.mp4", streaming.user_headers)
    assert res.status_code == 200
    assert res.content == SEGMENT
    assert res.headers["content-type"] == "video/mp4"
    assert "cache-control" not in res.headers
    assert streaming.fake.requests[0]["path"] == "/feeder/abc_seg3.mp4"


def test_hls_from_a_user_without_access_is_404(client, streaming, viewer_headers):
    assert _hls(client, streaming.id, "index.m3u8", viewer_headers).status_code == 404
    assert streaming.fake.requests == []


def test_hls_needs_a_user_jwt(client, streaming):
    assert _hls(client, streaming.id, "index.m3u8", {}).status_code == 401
    assert _hls(client, streaming.id, "index.m3u8", streaming.device_headers).status_code == 401
    assert streaming.fake.requests == []


def test_hls_without_live_url_is_503(client, owner_headers):
    res = _hls(client, IDS["dev1_id"], "index.m3u8", owner_headers)
    assert res.status_code == 503
    assert res.json()["detail"] == "feeder not streaming"


def test_hls_when_mediamtx_is_down_or_has_no_stream_is_503(client, streaming):
    streaming.fake.hls_status = 404
    assert _hls(client, streaming.id, "index.m3u8", streaming.user_headers).status_code == 503
    streaming.fake.close()
    assert _hls(client, streaming.id, "index.m3u8", streaming.user_headers).status_code == 503


def test_hls_refused_upstream_is_502(client, streaming):
    streaming.fake.hls_status = 401
    assert _hls(client, streaming.id, "index.m3u8", streaming.user_headers).status_code == 502


# httpx removes literal dot segments before sending, so the HTTP cases use the
# encoded forms. The pattern itself is checked with the literal ones below.
@pytest.mark.parametrize("name", [
    "..%2Fwhep",
    "%2E%2E/index.m3u8",
    "%2E%2E%2Fwhep",
    "sub/index.m3u8",
    "index.m3u8.html",
    "index",
    "http://8.8.8.8/index.m3u8",
    "//8.8.8.8/index.m3u8",
])
def test_hls_refuses_paths_mediamtx_does_not_serve(client, streaming, name):
    res = _hls(client, streaming.id, name, streaming.user_headers)
    assert res.status_code == 404
    assert streaming.fake.requests == []


@pytest.mark.parametrize("name", ["../whep", "..", "a/../index.m3u8", "/index.m3u8",
                                  "..m3u8", "index.m3u8?x", ""])
def test_hls_file_pattern_refuses_dot_segments(name):
    assert not hls.HLS_FILE.match(name)


def test_hls_url_keeps_the_host_and_swaps_the_port(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_HLS_PORT", 8888)
    assert hls.hls_url("http://192.168.4.104:8889/feeder/whep", "index.m3u8", "_HLS_msn=4") ==         "http://192.168.4.104:8888/feeder/index.m3u8?_HLS_msn=4"


def test_hls_caches_access_per_user_and_device(client, streaming):
    assert _hls(client, streaming.id, "abc_seg3.mp4", streaming.user_headers).status_code == 200
    # The Pi stops streaming. A cached viewer keeps going to MediaMTX for up
    # to 30 seconds, and MediaMTX answers for itself.
    client.post("/devices/me/heartbeat", json={"signal": "good"},
                headers=streaming.device_headers)
    assert _hls(client, streaming.id, "abc_seg3.mp4", streaming.user_headers).status_code == 200
    controller.clear_access_cache()
    assert _hls(client, streaming.id, "index.m3u8", streaming.user_headers).status_code == 503
