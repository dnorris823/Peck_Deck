"""Tier 2's pause switch: GET and PUT /tier2, relayed to a fake inference server.

The switch is owner only. A viewer sees the state and gets 403 on a change,
never 401, which would sign them out.
"""
import asyncio

import pytest
from aiohttp import web

from backend.classification import tier2
from backend.sightings.recheck import InferenceClient, SwitchRefused

TOKEN = "control-token-for-tests"


class FakeClient:
    def __init__(self, body=None, *, answers=True):
        self.body = body if body is not None else {
            "status": "ok", "model_ready": True, "state": "ready", "game_pause": True,
        }
        self.answers = answers
        self.refuse: SwitchRefused | None = None
        self.calls: list[bool] = []
        self.tokens: list[str] = []

    async def status(self):
        return self.body if self.answers else None

    async def set_paused(self, paused, token):
        self.calls.append(paused)
        self.tokens.append(token)
        if self.refuse is not None:
            raise self.refuse
        if not self.answers:
            return None
        self.body = {**self.body, "state": "paused_manual" if paused else "loading",
                     "model_ready": False}
        return self.body


@pytest.fixture
def server(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(tier2, "_client", lambda: fake)
    monkeypatch.setattr(tier2.settings, "INFERENCE_CONTROL_TOKEN", TOKEN)
    return fake


def test_any_user_reads_the_state(client, viewer_headers, server):
    server.body = {"status": "ok", "model_ready": False, "state": "paused_game",
                   "game_pause": True}

    res = client.get("/tier2", headers=viewer_headers)

    assert res.status_code == 200
    assert res.json() == {"state": "paused_game", "game_pause": True, "switch_off": None}


def test_a_server_that_does_not_answer_is_offline(client, owner_headers, server):
    server.answers = False

    assert client.get("/tier2", headers=owner_headers).json() == {
        "state": "offline", "game_pause": False, "switch_off": None,
    }


def test_an_older_server_without_a_state_reads_from_model_ready(client, owner_headers, server):
    server.body = {"status": "ok", "model_ready": True}

    assert client.get("/tier2", headers=owner_headers).json()["state"] == "ready"


def test_the_owner_pauses_and_resumes(client, owner_headers, server):
    res = client.put("/tier2", headers=owner_headers, json={"paused": True})
    assert res.status_code == 200
    assert res.json()["state"] == "paused_manual"

    res = client.put("/tier2", headers=owner_headers, json={"paused": False})
    assert res.json()["state"] == "loading"
    assert server.calls == [True, False]
    assert server.tokens == [TOKEN, TOKEN]


def test_a_viewer_gets_403_not_401(client, viewer_headers, server):
    res = client.put("/tier2", headers=viewer_headers, json={"paused": True})

    assert res.status_code == 403
    assert server.calls == []


def test_the_switch_needs_a_user(client, server):
    assert client.get("/tier2").status_code == 401
    assert client.put("/tier2", json={"paused": True}).status_code == 401


def test_a_switch_the_server_does_not_answer_is_503(client, owner_headers, server):
    server.answers = False

    res = client.put("/tier2", headers=owner_headers, json={"paused": True})

    assert res.status_code == 503


# ── The control token ─────────────────────────────────────────────────────────


def test_with_no_api_token_the_switch_refuses_and_says_why(client, owner_headers, server,
                                                           monkeypatch):
    monkeypatch.setattr(tier2.settings, "INFERENCE_CONTROL_TOKEN", "")

    assert client.get("/tier2", headers=owner_headers).json()["switch_off"] == tier2.NO_API_TOKEN
    res = client.put("/tier2", headers=owner_headers, json={"paused": True})
    assert res.status_code == 503
    assert res.json()["detail"] == tier2.NO_API_TOKEN
    assert server.calls == []


def test_a_server_with_no_token_turns_the_switch_off(client, owner_headers, server):
    server.body = {**server.body, "control": False}

    body = client.get("/tier2", headers=owner_headers).json()

    assert body["state"] == "ready"
    assert body["switch_off"] == tier2.NO_SERVER_TOKEN


def test_a_server_refusal_is_502_with_its_reason_never_401_or_403(client, owner_headers, server):
    server.refuse = SwitchRefused(403, "Wrong or missing control token")

    res = client.put("/tier2", headers=owner_headers, json={"paused": True})

    assert res.status_code == 502
    assert res.json()["detail"] == (
        "The GPU server refused the switch: Wrong or missing control token"
    )


# ── The HTTP relay ────────────────────────────────────────────────────────────


async def _with_server(handler, check):
    app = web.Application()
    app.add_routes([web.post("/pause", handler), web.post("/resume", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        return await check(InferenceClient(f"http://127.0.0.1:{port}"))
    finally:
        await runner.cleanup()


def test_the_relay_sends_the_token_as_a_bearer_header():
    seen = []

    async def handler(request):
        seen.append((request.path, request.headers.get("Authorization")))
        return web.json_response({"state": "paused_manual", "model_ready": False})

    body = asyncio.run(_with_server(handler, lambda c: c.set_paused(True, TOKEN)))

    assert body["state"] == "paused_manual"
    assert seen == [("/pause", f"Bearer {TOKEN}")]


@pytest.mark.parametrize(("status", "detail"), [
    (403, "Wrong or missing control token"),
    (503, "INFERENCE_CONTROL_TOKEN is not set on the GPU server"),
])
def test_the_relay_raises_the_servers_refusal(status, detail):
    async def handler(request):
        return web.json_response({"detail": detail}, status=status)

    with pytest.raises(SwitchRefused) as exc:
        asyncio.run(_with_server(handler, lambda c: c.set_paused(False, TOKEN)))

    assert exc.value.status == status
    assert exc.value.detail == detail


def test_the_relay_returns_none_when_the_server_does_not_answer():
    client = InferenceClient("http://127.0.0.1:9")

    assert asyncio.run(client.set_paused(True, TOKEN)) is None
