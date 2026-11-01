"""Tier 2's pause switch: GET and PUT /tier2, relayed to a fake inference server.

The switch is owner only. A viewer sees the state and gets 403 on a change,
never 401, which would sign them out.
"""
import pytest

from backend.classification import tier2


class FakeClient:
    def __init__(self, body=None, *, answers=True):
        self.body = body if body is not None else {
            "status": "ok", "model_ready": True, "state": "ready", "game_pause": True,
        }
        self.answers = answers
        self.calls: list[bool] = []

    async def status(self):
        return self.body if self.answers else None

    async def set_paused(self, paused):
        self.calls.append(paused)
        if not self.answers:
            return None
        self.body = {**self.body, "state": "paused_manual" if paused else "loading",
                     "model_ready": False}
        return self.body


@pytest.fixture
def server(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(tier2, "_client", lambda: fake)
    return fake


def test_any_user_reads_the_state(client, viewer_headers, server):
    server.body = {"status": "ok", "model_ready": False, "state": "paused_game",
                   "game_pause": True}

    res = client.get("/tier2", headers=viewer_headers)

    assert res.status_code == 200
    assert res.json() == {"state": "paused_game", "game_pause": True}


def test_a_server_that_does_not_answer_is_offline(client, owner_headers, server):
    server.answers = False

    assert client.get("/tier2", headers=owner_headers).json() == {
        "state": "offline", "game_pause": False,
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
