"""The game pause, with a fake classifier, a fake clock and fake GPU readings.

No torch and no NVML. ``Tier2Model`` loads through ``asyncio.to_thread``, so
the model tests run on an event loop.
"""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from inference_server import gaming, main
from inference_server.classifier import Prediction
from inference_server.gaming import (
    LOADING,
    PAUSED_GAME,
    PAUSED_MANUAL,
    READY,
    GameWatcher,
    Tier2Model,
)


class FakeClassifier:
    loads = 0

    def __init__(self):
        FakeClassifier.loads += 1
        self.unloaded = False

    def classify(self, image_bytes):
        return Prediction("Northern Cardinal", "Cardinalis cardinalis", 0.9)

    def unload(self):
        self.unloaded = True


def run(coro):
    return asyncio.run(coro)


# ── Tier2Model ────────────────────────────────────────────────────────────────


def test_model_loads_then_pauses_and_unloads():
    async def go():
        model = Tier2Model(FakeClassifier)
        model.resume()
        assert model.state == LOADING
        assert model.classifier is None
        await model.wait_loaded()
        assert model.state == READY
        clf = model.classifier
        assert clf is not None

        model.pause(PAUSED_GAME)
        assert model.state == PAUSED_GAME
        assert model.classifier is None
        assert clf.unloaded

    run(go())


def test_model_load_failure_is_failed_and_a_resume_retries():
    async def go():
        model = Tier2Model(lambda: None)
        model.resume()
        await model.wait_loaded()
        assert model.state == "failed"
        model._load_fn = FakeClassifier
        model.resume()
        await model.wait_loaded()
        assert model.state == READY

    run(go())


def test_a_pause_during_a_load_frees_the_model_when_the_load_ends():
    async def go():
        loaded = []

        def slow_load():
            import time

            time.sleep(0.05)
            clf = FakeClassifier()
            loaded.append(clf)
            return clf

        model = Tier2Model(slow_load)
        model.resume()
        model.pause(PAUSED_MANUAL)
        assert model.state == PAUSED_MANUAL
        await model.wait_loaded()
        assert model.state == PAUSED_MANUAL
        assert model.classifier is None
        assert loaded[0].unloaded

    run(go())


def test_a_resume_during_a_load_starts_no_second_load():
    async def go():
        FakeClassifier.loads = 0
        model = Tier2Model(FakeClassifier)
        model.resume()
        model.pause(PAUSED_MANUAL)
        model.resume(manual=True)
        await model.wait_loaded()
        assert FakeClassifier.loads == 1
        assert model.state == READY

    run(go())


# ── GameWatcher ───────────────────────────────────────────────────────────────


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Gpu:
    def __init__(self, use=0.0):
        self.use = use

    def __call__(self):
        return self.use


def ready_model() -> Tier2Model:
    model = Tier2Model(FakeClassifier)
    model._classifier = FakeClassifier()
    model._state = READY
    return model


def watcher(model, gpu, clock, **kw):
    opts = dict(pause_percent=50, pause_after=30, resume_percent=15, resume_after=300,
                sample_seconds=2)
    opts.update(kw)
    return GameWatcher(model, gpu, clock=clock, **opts)


def ticks(w, clock, seconds, step=2):
    for _ in range(int(seconds / step)):
        w.tick()
        clock.now += step


def test_a_game_pauses_tier2_after_30_seconds_not_before():
    model, gpu, clock = ready_model(), Gpu(90), Clock()
    w = watcher(model, gpu, clock)
    ticks(w, clock, 26)
    assert model.state == READY
    ticks(w, clock, 6)
    assert model.state == PAUSED_GAME


def test_a_short_burst_and_a_quiet_desktop_never_pause():
    model, gpu, clock = ready_model(), Gpu(5), Clock()
    w = watcher(model, gpu, clock)
    ticks(w, clock, 60)
    gpu.use = 100
    ticks(w, clock, 10)
    gpu.use = 5
    ticks(w, clock, 60)
    assert model.state == READY


def test_tier2_resumes_after_five_quiet_minutes():
    async def go():
        model, gpu, clock = ready_model(), Gpu(90), Clock()
        w = watcher(model, gpu, clock)
        ticks(w, clock, 40)
        assert model.state == PAUSED_GAME
        gpu.use = 3
        ticks(w, clock, 240)
        assert model.state == PAUSED_GAME
        ticks(w, clock, 80)
        assert model.state == LOADING
        await model.wait_loaded()
        assert model.state == READY

    run(go())


def test_the_watcher_never_resumes_a_manual_pause():
    model, gpu, clock = ready_model(), Gpu(0), Clock()
    model.pause(PAUSED_MANUAL)
    w = watcher(model, gpu, clock)
    ticks(w, clock, 400)
    assert model.state == PAUSED_MANUAL


def test_readings_after_our_own_classify_calls_are_skipped():
    model, gpu, clock = ready_model(), Gpu(100), Clock()
    w = watcher(model, gpu, clock)
    for _ in range(30):
        # A re-check backlog: one classify per reading.
        model.last_busy = clock.now - 0.5
        w.tick()
        clock.now += 2
    assert model.state == READY


def test_the_owners_resume_holds_off_the_game_until_the_gpu_goes_quiet():
    async def go():
        model, gpu, clock = ready_model(), Gpu(90), Clock()
        w = watcher(model, gpu, clock)
        ticks(w, clock, 40)
        assert model.state == PAUSED_GAME

        model.resume(manual=True)
        await model.wait_loaded()
        ticks(w, clock, 120)
        assert model.state == READY, "the running game must not pause it again"

        gpu.use = 5
        ticks(w, clock, 40)
        assert not model.hold_game_pause
        gpu.use = 90
        ticks(w, clock, 40)
        assert model.state == PAUSED_GAME, "the next game pauses it"

    run(go())


def test_bad_thresholds_refuse_to_start():
    with pytest.raises(ValueError):
        watcher(ready_model(), Gpu(), Clock(), pause_percent=10, resume_percent=20)


def test_a_cpu_device_has_no_reader():
    assert gaming.nvml_reader("cpu") is None


# ── The endpoints ─────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_load_classifier", FakeClassifier)
    monkeypatch.setattr(main.settings, "GAME_PAUSE_ENABLED", False)
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
    assert body == {"status": "ok", "model_ready": True, "state": READY, "game_pause": False}


def test_pause_returns_503_with_the_reason_and_resume_answers_again(client):
    assert classify(client).status_code == 200

    body = client.post("/pause").json()
    assert body["state"] == PAUSED_MANUAL
    assert body["model_ready"] is False
    resp = classify(client)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Tier 2 is paused by the owner"

    assert client.post("/resume").json()["state"] in (LOADING, READY)
    wait_for(client, READY)
    assert classify(client).status_code == 200


def test_a_game_pause_says_so(client):
    main._model.pause(PAUSED_GAME)
    resp = classify(client)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Tier 2 is paused while a game runs"
