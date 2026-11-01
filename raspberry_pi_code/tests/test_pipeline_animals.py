"""Tier 2's animal answer in ``Pipeline._classify`` and on the upload path.

A squirrel that Tier 2 names above ``TIER2_ANIMAL_THRESHOLD``, and above its
best bird, records as an animal. Tier 1 and Tier 3 never run for it, because
Tier 1 knows birds only and Tier 3 costs money. Below the bar the bird chain
runs as it always has.
"""
import asyncio
import json
from pathlib import Path

import aiohttp
from aiohttp import web

from raspberry_pi_code.api_client import BackendClient, UploadOutcome
from raspberry_pi_code.classification.base import (
    AnimalAnswer,
    ClassificationResult,
    ClassifierBase,
)
from raspberry_pi_code.classification.tier2_gpu import GPUServerClassifier
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline
from raspberry_pi_code.storage.local_cache import LocalCache, QueuedSighting

_IMAGE = Path("capture.jpg")

_SQUIRREL = AnimalAnswer(
    common_name="Eastern Gray Squirrel",
    scientific_name="Sciurus carolinensis",
    group="squirrel",
    confidence=0.81,
)


class _Stub(ClassifierBase):
    def __init__(self, tier: str, confidence: float | None, animal: AnimalAnswer | None = None):
        self._tier = tier
        self._confidence = confidence
        self._animal = animal
        self.calls = 0

    @property
    def tier_name(self) -> str:
        return self._tier

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        self.calls += 1
        if self._confidence is None:
            return None
        return ClassificationResult(
            common_name=f"{self._tier}-bird",
            scientific_name=f"Genus {self._tier}",
            confidence=self._confidence,
            tier_used=self._tier,
            animal=self._animal,
        )


def _pipeline(tmp_path, **overrides) -> Pipeline:
    cfg = Config(cache_dir=str(tmp_path / "cache"), device_token="t", **overrides)
    return Pipeline(cfg)


def _classify(pipeline: Pipeline, *chain: _Stub):
    pipeline._classifiers_for_preference = lambda: list(chain)
    result, trace = asyncio.run(pipeline._classify(_IMAGE))
    return result, [(a.tier, a.outcome, a.confidence, a.threshold) for a in trace]


def _animal(confidence: float) -> AnimalAnswer:
    return AnimalAnswer(_SQUIRREL.common_name, _SQUIRREL.scientific_name, "squirrel", confidence)


# ── The chain ───────────────────────────────────────────────────────────────

def test_a_squirrel_tier2_names_is_an_animal_and_tier1_never_runs(tmp_path):
    tier2 = _Stub("gpu", 0.04, animal=_SQUIRREL)
    tier1 = _Stub("local", 0.95)
    pipeline = _pipeline(tmp_path, tier2_animal_threshold=0.5)

    result, trace = _classify(pipeline, tier2, tier1)

    assert result.common_name == "Eastern Gray Squirrel"
    assert result.scientific_name == "Sciurus carolinensis"
    assert result.animal_group == "squirrel"
    assert result.confidence == 0.81
    assert result.tier_used == "gpu"
    assert tier1.calls == 0, "Tier 1 knows birds only and must not name the squirrel"
    assert trace == [("gpu", "accepted", 0.81, 0.5), ("local", "not_run", None, 0.85)]


def test_a_squirrel_never_reaches_tier3(tmp_path):
    tier3 = _Stub("cloud", 0.99)
    tier2 = _Stub("gpu", 0.04, animal=_SQUIRREL)
    tier1 = _Stub("local", 0.99)

    result, _ = _classify(_pipeline(tmp_path, tier2_animal_threshold=0.5), tier2, tier1, tier3)

    assert result.animal_group == "squirrel"
    assert (tier1.calls, tier3.calls) == (0, 0)


def test_a_squirrel_below_the_animal_bar_runs_the_bird_chain(tmp_path):
    tier2 = _Stub("gpu", 0.10, animal=_animal(0.30))
    tier1 = _Stub("local", 0.90)

    result, trace = _classify(_pipeline(tmp_path, tier2_animal_threshold=0.5), tier2, tier1)

    assert tier1.calls == 1
    assert result.tier_used == "local"
    assert result.animal_group is None
    assert trace == [("gpu", "below_threshold", 0.10, 0.60), ("local", "accepted", 0.90, 0.85)]


def test_an_animal_that_does_not_beat_the_bird_loses(tmp_path):
    # Both clear their bars. The bird scores higher, so it is a bird.
    tier2 = _Stub("gpu", 0.70, animal=_animal(0.65))

    result, _ = _classify(_pipeline(tmp_path, tier2_animal_threshold=0.5), tier2)

    assert result.common_name == "gpu-bird"
    assert result.animal_group is None


def test_the_animal_bar_is_inclusive_like_the_tier_bars(tmp_path):
    tier2 = _Stub("gpu", 0.10, animal=_animal(0.5))

    result, _ = _classify(_pipeline(tmp_path, tier2_animal_threshold=0.5), tier2)

    assert result.animal_group == "squirrel"


def test_an_old_inference_server_with_no_animal_runs_the_bird_chain(tmp_path):
    tier2 = _Stub("gpu", 0.72)

    result, _ = _classify(_pipeline(tmp_path), tier2)

    assert result.common_name == "gpu-bird"
    assert result.animal_group is None


def test_animal_threshold_reads_from_the_environment(monkeypatch):
    import importlib

    import raspberry_pi_code.config as config_module

    monkeypatch.setenv("TIER2_ANIMAL_THRESHOLD", "0.42")
    reloaded = importlib.reload(config_module)
    try:
        assert reloaded.Config().tier2_animal_threshold == 0.42
    finally:
        monkeypatch.delenv("TIER2_ANIMAL_THRESHOLD")
        importlib.reload(config_module)


# ── Upload and queue ────────────────────────────────────────────────────────

class _FileCamera:
    async def capture(self, output_path: Path) -> Path:
        output_path.write_bytes(b"\xff\xd8 not really a jpeg")
        return output_path


class _RecordingClient:
    def __init__(self, outcome: UploadOutcome):
        self.outcome = outcome
        self.posts: list[dict] = []

    async def post_sighting(self, **kwargs) -> UploadOutcome:
        self.posts.append(kwargs)
        return self.outcome

    async def is_reachable(self) -> bool:
        return True


def _squirrel_pipeline(tmp_path, outcome: UploadOutcome) -> tuple[Pipeline, _RecordingClient]:
    pipeline = Pipeline(
        Config(cache_dir=str(tmp_path / "cache"), device_token="t", tier2_animal_threshold=0.5),
        camera=_FileCamera(),
    )
    pipeline._cache.setup()
    pipeline._tier2 = _Stub("gpu", 0.04, animal=_SQUIRREL)
    pipeline._tier1 = _Stub("local", 0.95)
    client = _RecordingClient(outcome)
    pipeline._client = client
    return pipeline, client


async def _visit(pipeline: Pipeline) -> None:
    await pipeline._process(await pipeline._capture())


def test_an_animal_sighting_uploads_with_its_group(tmp_path):
    pipeline, client = _squirrel_pipeline(tmp_path, UploadOutcome.OK)

    asyncio.run(_visit(pipeline))

    [post] = client.posts
    assert post["common_name"] == "Eastern Gray Squirrel"
    assert post["animal_group"] == "squirrel"
    assert post["tier_used"] == "gpu"
    assert pipeline._tier1.calls == 0


def test_a_bird_sighting_uploads_with_no_group(tmp_path):
    pipeline, client = _squirrel_pipeline(tmp_path, UploadOutcome.OK)
    pipeline._tier2 = _Stub("gpu", 0.90)

    asyncio.run(_visit(pipeline))

    assert client.posts[0]["animal_group"] is None


def test_a_queued_animal_keeps_its_group_through_sync(tmp_path):
    pipeline, client = _squirrel_pipeline(tmp_path, UploadOutcome.RETRY)

    asyncio.run(_visit(pipeline))
    [queued] = pipeline._cache.get_pending()
    assert queued.animal_group == "squirrel"

    client.outcome = UploadOutcome.OK
    asyncio.run(pipeline.sync_offline_queue())

    assert client.posts[-1]["animal_group"] == "squirrel"
    assert client.posts[-1]["delayed"] is True
    assert pipeline._cache.get_pending() == []


def test_a_queue_row_from_an_older_build_reads_as_a_bird(tmp_path):
    cache = LocalCache(str(tmp_path / "cache"))
    cache.setup()
    old_row = {
        "id": "e1", "timestamp": "2026-10-31T12:00:00+00:00", "image_path": "x.jpg",
        "common_name": "Blue Jay", "scientific_name": "Cyanocitta cristata",
        "confidence": 0.9, "tier_used": "gpu", "tier_trace": None,
    }
    (tmp_path / "cache" / "queue.json").write_text(json.dumps([old_row]))

    [row] = cache.get_pending()

    assert row == QueuedSighting(**old_row)
    assert row.animal_group is None


# ── Over HTTP ───────────────────────────────────────────────────────────────

async def _serve(handler, path: str):
    app = web.Application()
    app.router.add_post(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_tier2_client_reads_the_animal_field(tmp_path):
    image = tmp_path / "c.jpg"
    image.write_bytes(b"\xff\xd8 jpeg")

    async def handler(request):
        return web.json_response({
            "common_name": "Blue Jay", "scientific_name": "Cyanocitta cristata",
            "confidence": 0.03,
            "animal": {"common_name": "Eastern Gray Squirrel",
                       "scientific_name": "Sciurus carolinensis",
                       "group": "squirrel", "confidence": 0.88},
        })

    async def go():
        runner, url = await _serve(handler, "/classify")
        try:
            return await GPUServerClassifier(url).classify(image)
        finally:
            await runner.cleanup()

    result = asyncio.run(go())

    assert result.common_name == "Blue Jay"
    assert result.animal == AnimalAnswer(
        "Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.88
    )


def test_tier2_client_keeps_the_bird_when_the_animal_field_is_malformed(tmp_path):
    image = tmp_path / "c.jpg"
    image.write_bytes(b"\xff\xd8 jpeg")

    async def handler(request):
        return web.json_response({
            "common_name": "Blue Jay", "scientific_name": "Cyanocitta cristata",
            "confidence": 0.91, "animal": {"group": "squirrel"},
        })

    async def go():
        runner, url = await _serve(handler, "/classify")
        try:
            return await GPUServerClassifier(url).classify(image)
        finally:
            await runner.cleanup()

    result = asyncio.run(go())

    assert result.confidence == 0.91
    assert result.animal is None


def test_backend_client_sends_kind_and_group_only_for_an_animal(tmp_path):
    image = tmp_path / "c.jpg"
    image.write_bytes(b"\xff\xd8 jpeg")
    seen: list[dict] = []

    async def handler(request):
        form = await request.post()
        seen.append({k: v for k, v in form.items() if k != "image"})
        return web.json_response({}, status=201)

    async def go():
        runner, url = await _serve(handler, "/sightings")
        try:
            client = BackendClient(url, "t")
            common = dict(image_path=image, timestamp="2026-10-31T12:00:00+00:00",
                          scientific_name="x y", confidence=0.8, tier_used="gpu")
            await client.post_sighting(common_name="Eastern Gray Squirrel",
                                       animal_group="squirrel", **common)
            await client.post_sighting(common_name="Blue Jay", **common)
        finally:
            await runner.cleanup()

    asyncio.run(go())

    assert seen[0]["kind"] == "animal"
    assert seen[0]["animal_group"] == "squirrel"
    assert "kind" not in seen[1] and "animal_group" not in seen[1]
