"""Weather on new sightings, from Open-Meteo.

Every test stubs ``weather._get_json``, the module's only network call, and
conftest makes an unstubbed call fail. So nothing here reaches Open-Meteo.

Each upload goes to a fresh device owned by a throwaway user, so the seeded
counts in test_sightings.py stay exact.
"""
import asyncio
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import backend.sightings.aftercare as sighting_aftercare
from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, Species, User
from backend.events.hub import SightingUpdated
from backend.sightings import weather

_JPEG = b"\xff\xd8\xff\xe0weather-bytes"

BURLINGTON_VT = {"name": "Burlington", "latitude": 44.48, "longitude": -73.21,
                 "admin1": "Vermont", "country_code": "US"}
BURLINGTON_NC = {"name": "Burlington", "latitude": 36.10, "longitude": -79.44,
                 "admin1": "North Carolina", "country_code": "US"}


class FakeOpenMeteo:
    """Answers the geocoder and the forecast API, and counts the calls."""

    def __init__(self, places=(BURLINGTON_VT,), temperature=3.6, code=71):
        self.places = list(places)
        self.temperature = temperature
        self.code = code
        self.geocode_calls = 0
        self.forecast_calls = []

    async def __call__(self, url, params):
        if url == weather.GEOCODE_URL:
            self.geocode_calls += 1
            return {"results": self.places} if self.places else {}
        assert url == weather.FORECAST_URL
        self.forecast_calls.append(params)
        return {"hourly": {"time": [params["start_hour"]],
                           "temperature_2m": [self.temperature],
                           "weather_code": [self.code]}}


@pytest.fixture
def weather_on(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(weather, "_geocode_cache", {})
    published = []
    monkeypatch.setattr(weather.sighting_hub, "publish", published.append)
    return published


def _silence_aftercare(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _noop)


async def _device(city, state) -> tuple[int, str]:
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(name="Weather Owner", email=f"weather_{secrets.token_hex(4)}@test.dev",
                     password_hash="x", role="owner", notify_email=False)
            db.add(u)
            await db.flush()
            token = secrets.token_urlsafe(12)
            d = Device(name="Weather Device", city=city, state=state, owner_id=u.id, token=token)
            db.add(d)
            await db.flush()
            return d.id, token


async def _sighting(device_id, when=None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = (await db.execute(select(Species).limit(1))).scalar_one()
            s = Sighting(species_id=sp.id, device_id=device_id,
                         datetime=when or datetime.now(timezone.utc),
                         classification_tier_used="gpu", confidence_score=0.9, delayed=False)
            db.add(s)
            await db.flush()
            return s.id


async def _weather_of(sighting_id):
    async with get_session_factory()() as db:
        return (await db.execute(
            select(Sighting.weather_conditions).where(Sighting.id == sighting_id)
        )).scalar_one()


def _upload(client, token):
    return client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data={"timestamp": datetime.now(timezone.utc).isoformat(),
              "common_name": "Weather Wren", "scientific_name": "Troglodytes testus",
              "confidence_score": "0.9", "classification_tier_used": "gpu"},
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )


def _wait_for_weather(sighting_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = asyncio.run(_weather_of(sighting_id))
        if value is not None:
            return value
        time.sleep(0.05)
    return None


# ---------------------------------------------------------------------------
# The string
# ---------------------------------------------------------------------------
def test_describe_rounds_and_names_the_code():
    assert weather.describe(3.6, 71) == "4 °C, light snow"
    assert weather.describe(-0.4, 0) == "0 °C, clear sky"


def test_describe_without_a_known_code_keeps_the_temperature():
    assert weather.describe(12.2, 42) == "12 °C"
    assert weather.describe(12.2, None) == "12 °C"


def test_describe_without_a_temperature_is_none():
    assert weather.describe(None, 3) is None


# ---------------------------------------------------------------------------
# Geocoding and its cache
# ---------------------------------------------------------------------------
def test_geocode_picks_the_result_in_the_device_state(monkeypatch):
    monkeypatch.setattr(weather, "_geocode_cache", {})
    fake = FakeOpenMeteo(places=[BURLINGTON_NC, BURLINGTON_VT])
    monkeypatch.setattr(weather, "_get_json", fake)

    assert asyncio.run(weather.geocode("Burlington", "VT")) == (44.48, -73.21)
    assert asyncio.run(weather.geocode("Burlington", "North Carolina")) == (36.10, -79.44)


def test_geocode_with_no_match_in_the_state_is_none(monkeypatch):
    monkeypatch.setattr(weather, "_geocode_cache", {})
    monkeypatch.setattr(weather, "_get_json", FakeOpenMeteo(places=[BURLINGTON_NC]))

    assert asyncio.run(weather.geocode("Burlington", "VT")) is None


def test_geocode_is_cached_per_city(monkeypatch):
    monkeypatch.setattr(weather, "_geocode_cache", {})
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "_get_json", fake)

    asyncio.run(weather.geocode("Burlington", "VT"))
    asyncio.run(weather.geocode(" burlington ", "vt"))

    assert fake.geocode_calls == 1


def test_an_unknown_city_is_cached_too(monkeypatch):
    monkeypatch.setattr(weather, "_geocode_cache", {})
    fake = FakeOpenMeteo(places=[])
    monkeypatch.setattr(weather, "_get_json", fake)

    assert asyncio.run(weather.geocode("Nowhere", "VT")) is None
    assert asyncio.run(weather.geocode("Nowhere", "VT")) is None
    assert fake.geocode_calls == 1


def test_a_failed_geocode_is_not_cached(monkeypatch):
    monkeypatch.setattr(weather, "_geocode_cache", {})

    async def down(url, params):
        raise weather.LookupFailed("down")

    monkeypatch.setattr(weather, "_get_json", down)
    with pytest.raises(weather.LookupFailed):
        asyncio.run(weather.geocode("Burlington", "VT"))
    assert weather._geocode_cache == {}


# ---------------------------------------------------------------------------
# fill_weather
# ---------------------------------------------------------------------------
def test_fill_weather_stores_the_string_and_tells_open_tabs(client, weather_on, monkeypatch):
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "_get_json", fake)
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    sid = asyncio.run(_sighting(device_id))

    asyncio.run(weather.fill_weather(sid))

    assert asyncio.run(_weather_of(sid)) == "4 °C, light snow"
    [event] = weather_on
    assert isinstance(event, SightingUpdated)
    assert event.payload["weather_conditions"] == "4 °C, light snow"


def test_each_sighting_after_the_first_makes_one_call(client, weather_on, monkeypatch):
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "_get_json", fake)
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    first, second = asyncio.run(_sighting(device_id)), asyncio.run(_sighting(device_id))

    asyncio.run(weather.fill_weather(first))
    asyncio.run(weather.fill_weather(second))

    assert fake.geocode_calls == 1
    assert len(fake.forecast_calls) == 2


def test_fill_weather_asks_for_the_capture_hour(client, weather_on, monkeypatch):
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "_get_json", fake)
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    when = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=14, minute=40)
    sid = asyncio.run(_sighting(device_id, when))

    asyncio.run(weather.fill_weather(sid))

    expected = when.replace(hour=15, minute=0).strftime("%Y-%m-%dT%H:%M")
    assert fake.forecast_calls[0]["start_hour"] == expected
    assert fake.forecast_calls[0]["end_hour"] == expected


def test_a_sighting_older_than_the_forecast_api_keeps_no_weather(client, weather_on, monkeypatch):
    fake = FakeOpenMeteo()
    monkeypatch.setattr(weather, "_get_json", fake)
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    sid = asyncio.run(_sighting(device_id, datetime.now(timezone.utc) - timedelta(days=200)))

    asyncio.run(weather.fill_weather(sid))

    assert asyncio.run(_weather_of(sid)) is None
    assert fake.geocode_calls == 0


@pytest.mark.parametrize("city", [None, "", "   "])
def test_a_device_with_no_city_makes_no_call(client, weather_on, city):
    # The conftest guard fails the test if anything reaches _get_json.
    device_id, _ = asyncio.run(_device(city, "VT"))
    sid = asyncio.run(_sighting(device_id))

    asyncio.run(weather.fill_weather(sid))

    assert asyncio.run(_weather_of(sid)) is None
    assert weather_on == []


def test_an_open_meteo_failure_leaves_the_field_empty(client, weather_on, monkeypatch):
    async def down(url, params):
        raise weather.LookupFailed("503")

    monkeypatch.setattr(weather, "_get_json", down)
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    sid = asyncio.run(_sighting(device_id))

    asyncio.run(weather.fill_weather(sid))  # does not raise

    assert asyncio.run(_weather_of(sid)) is None
    assert weather_on == []


# ---------------------------------------------------------------------------
# Through POST /sightings
# ---------------------------------------------------------------------------
def test_upload_at_a_device_with_a_city_gets_weather(client, weather_on, monkeypatch):
    _silence_aftercare(monkeypatch)
    monkeypatch.setattr(weather, "_get_json", FakeOpenMeteo())
    _, token = asyncio.run(_device("Burlington", "VT"))

    res = _upload(client, token)

    assert res.status_code == 201
    # The response goes out before the lookup runs.
    assert res.json()["weather_conditions"] is None
    assert _wait_for_weather(res.json()["id"]) == "4 °C, light snow"


def test_upload_at_a_device_with_no_city_succeeds_without_weather(client, weather_on, monkeypatch):
    _silence_aftercare(monkeypatch)
    _, token = asyncio.run(_device(None, None))

    res = _upload(client, token)

    assert res.status_code == 201
    assert _wait_for_weather(res.json()["id"], timeout=0.3) is None


def test_a_slow_then_failed_lookup_does_not_delay_or_fail_the_upload(client, weather_on, monkeypatch):
    _silence_aftercare(monkeypatch)
    release = threading.Event()

    async def hangs_then_fails(url, params):
        while not release.is_set():
            await asyncio.sleep(0.01)
        raise weather.LookupFailed("timed out")

    monkeypatch.setattr(weather, "_get_json", hangs_then_fails)
    _, token = asyncio.run(_device("Burlington", "VT"))

    started = time.monotonic()
    res = _upload(client, token)
    elapsed = time.monotonic() - started
    release.set()

    assert res.status_code == 201
    assert elapsed < 2.0, f"the upload waited on the weather lookup for {elapsed:.1f}s"
    assert _wait_for_weather(res.json()["id"], timeout=0.3) is None


def test_weather_disabled_makes_no_call(client, weather_on, monkeypatch):
    _silence_aftercare(monkeypatch)
    monkeypatch.setattr(settings, "WEATHER_ENABLED", False)
    _, token = asyncio.run(_device("Burlington", "VT"))

    res = _upload(client, token)

    assert res.status_code == 201
    assert _wait_for_weather(res.json()["id"], timeout=0.3) is None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_export_carries_the_weather(client, weather_on, monkeypatch):
    monkeypatch.setattr(weather, "_get_json", FakeOpenMeteo())
    device_id, _ = asyncio.run(_device("Burlington", "VT"))
    sid = asyncio.run(_sighting(device_id))
    asyncio.run(weather.fill_weather(sid))

    async def _owner_id():
        async with get_session_factory()() as db:
            return (await db.execute(
                select(Device.owner_id).where(Device.id == device_id)
            )).scalar_one()

    from backend.auth.jwt_utils import create_user_token

    headers = {"Authorization": f"Bearer {create_user_token(asyncio.run(_owner_id()), 'owner')}"}
    res = client.get("/sightings/export?fmt=csv", headers=headers)

    assert res.status_code == 200
    header, row = res.text.strip().splitlines()[:2]
    assert "weather_conditions" in header.split(",")
    assert "4 °C, light snow" in row
