"""The inference server's routes: /health, /classify, /pause and /resume.

Needs FastAPI, which the backend CI job does not install. Without it this file
skips, and the integration job's contract tests cover the routes.
"""
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from inference_server import main  # noqa: E402
from inference_server.gaming import LOADING, PAUSED_GAME, PAUSED_MANUAL, READY  # noqa: E402
from inference_server.tests.test_gaming import FakeClassifier  # noqa: E402

TOKEN = "control-token-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_load_classifier", FakeClassifier)
    monkeypatch.setattr(main.settings, "GAME_PAUSE_ENABLED", False)
    monkeypatch.setattr(main.settings, "INFERENCE_CONTROL_TOKEN", TOKEN)
    with TestClient(main.app) as c:
        wait_for(c, READY)
        yield c


def wait_for(c, state):
    for _ in range(200):
        if c.get("/health").json()["state"] == state:
            return
        time.sleep(0.01)
    raise AssertionError(f"state never became {state}")


def classify(c):
    return c.post("/classify", files={"image": ("b.jpg", b"jpeg", "image/jpeg")})


def test_health_reports_the_state(client):
    body = client.get("/health").json()
    assert body == {
        "status": "ok", "model_ready": True, "state": READY, "game_pause": False, "control": True,
    }


def test_pause_returns_503_with_the_reason_and_resume_answers_again(client):
    assert classify(client).status_code == 200

    body = client.post("/pause", headers=AUTH).json()
    assert body["state"] == PAUSED_MANUAL
    assert body["model_ready"] is False
    resp = classify(client)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Tier 2 is paused by the owner"

    assert client.post("/resume", headers=AUTH).json()["state"] in (LOADING, READY)
    wait_for(client, READY)
    assert classify(client).status_code == 200


def test_a_game_pause_says_so(client):
    main._model.pause(PAUSED_GAME)
    resp = classify(client)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Tier 2 is paused while a game runs"


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong-token"},
    {"Authorization": TOKEN},
    {"Authorization": "Basic " + TOKEN},
])
@pytest.mark.parametrize("path", ["/pause", "/resume"])
def test_the_switch_refuses_a_missing_or_wrong_token(client, path, headers):
    resp = client.post(path, headers=headers)

    assert resp.status_code == 403
    assert client.get("/health").json()["state"] == READY


def test_with_no_token_set_both_routes_refuse(client, monkeypatch):
    monkeypatch.setattr(main.settings, "INFERENCE_CONTROL_TOKEN", "")

    for path in ("/pause", "/resume"):
        resp = client.post(path, headers={"Authorization": "Bearer "})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "INFERENCE_CONTROL_TOKEN is not set on the GPU server"
    body = client.get("/health").json()
    assert body["state"] == READY
    assert body["control"] is False
    # Health and classify need no token.
    assert classify(client).status_code == 200
