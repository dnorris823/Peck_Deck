"""Weather at the feeder when a bird visited, from Open-Meteo.

Open-Meteo needs no API key. A lookup is two calls: the geocoder turns the
device's city and state into coordinates, then the forecast API gives the
temperature and WMO weather code for the capture hour. The geocode result is
cached per city, so a sighting after the first makes one call.

Runs after the upload response, in its own task and its own database sessions.
A failed lookup logs and leaves ``weather_conditions`` null. It never reaches
the Pi.
"""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select, update

from ..config import settings
from ..database.connection import get_session_factory
from ..database.models import Device, Sighting
from ..events.hub import SightingUpdated, sighting_hub
from .operations import HAS_IMAGE, SKIP_IMAGE
from .schemas import sighting_response

logger = logging.getLogger("peckdeck.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = aiohttp.ClientTimeout(total=8)

# The forecast API keeps about three months of past hours. An offline queue
# older than that gets no weather rather than a wrong one.
MAX_AGE = timedelta(days=92)

# WMO weather interpretation codes, as Open-Meteo documents them.
WMO_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}

# The geocoder reports a US state by its full name in `admin1`. Devices store
# whatever the owner typed, which is often the postal code.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

# Keyed by the normalised (city, state). A value of None means the geocoder has
# no such place, which is cached too. A failed request is not cached, so the
# next sighting tries again.
_geocode_cache: dict[tuple[str, str], tuple[float, float] | None] = {}


class LookupFailed(Exception):
    """Open-Meteo could not be reached, or answered with an error."""


async def _get_json(url: str, params: dict) -> dict:
    """One GET to Open-Meteo. The only function here that touches the network."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise LookupFailed(f"{url} answered {resp.status}")
                return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise LookupFailed(f"{url}: {exc!r}") from exc


def _cache_key(city: str, state: str | None) -> tuple[str, str]:
    return city.strip().lower(), (state or "").strip().lower()


def _state_matches(result: dict, state: str) -> bool:
    want = state.strip().lower()
    full = US_STATES.get(state.strip().upper(), "").lower()
    admin1 = (result.get("admin1") or "").lower()
    return admin1 in {want, full} or (result.get("admin1_code") or "").lower() == want


async def geocode(city: str, state: str | None) -> tuple[float, float] | None:
    """Coordinates for a city, or None if the geocoder has no such place.

    With a state, only a result in that state counts, because Burlington VT and
    Burlington NC have different weather. Without one, the geocoder's first
    result wins. Raises LookupFailed when Open-Meteo is unreachable.
    """
    key = _cache_key(city, state)
    if key in _geocode_cache:
        return _geocode_cache[key]

    data = await _get_json(
        GEOCODE_URL, {"name": city.strip(), "count": 10, "language": "en", "format": "json"}
    )
    results = data.get("results") or []
    if state and state.strip():
        results = [r for r in results if _state_matches(r, state)]
    place = (results[0]["latitude"], results[0]["longitude"]) if results else None
    _geocode_cache[key] = place
    return place


def describe(temperature: float | None, code: int | None) -> str | None:
    """The stored string, such as "4 °C, light snow". None with no temperature."""
    if temperature is None:
        return None
    text = f"{round(temperature)} °C"
    words = WMO_CODES.get(code) if code is not None else None
    return f"{text}, {words}" if words else text


async def conditions_at(lat: float, lon: float, when: datetime) -> str | None:
    """The weather string for the hour nearest ``when``, in UTC.

    Hourly data, not "current", so a sighting the Pi queued while offline gets
    the weather from when the bird was there.
    """
    hour = (when.astimezone(timezone.utc) + timedelta(minutes=30)).replace(
        minute=0, second=0, microsecond=0
    )
    stamp = hour.strftime("%Y-%m-%dT%H:%M")
    data = await _get_json(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,weather_code",
            "timezone": "GMT",
            "start_hour": stamp,
            "end_hour": stamp,
        },
    )
    hourly = data.get("hourly") or {}
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    if not temps:
        return None
    return describe(temps[0], codes[0] if codes else None)


async def lookup(city: str, state: str | None, when: datetime) -> str | None:
    """The weather string for a place and time, or None. Raises LookupFailed."""
    if datetime.now(timezone.utc) - when > MAX_AGE:
        return None
    place = await geocode(city, state)
    if place is None:
        logger.info("Open-Meteo has no place called %r, %r", city, state)
        return None
    return await conditions_at(*place, when)


async def fill_weather(sighting_id: int) -> None:
    """Background task: store the weather on a new sighting. Never raises.

    The database session closes before the network calls, so a slow Open-Meteo
    never holds a pooled connection. Writes only into an empty column, then
    tells open tabs, so a detail view already showing the sighting updates.
    """
    try:
        factory = get_session_factory()
        async with factory() as db:
            row = (
                await db.execute(
                    select(Sighting.datetime, Sighting.weather_conditions, Device.city, Device.state)
                    .join(Device, Device.id == Sighting.device_id)
                    .where(Sighting.id == sighting_id)
                )
            ).one_or_none()
        if row is None or row.weather_conditions or not (row.city and row.city.strip()):
            return

        when = row.datetime if row.datetime.tzinfo else row.datetime.replace(tzinfo=timezone.utc)
        text = await lookup(row.city, row.state, when)
        if text is None:
            return

        async with factory() as db:
            async with db.begin():
                done = await db.execute(
                    update(Sighting)
                    .where(Sighting.id == sighting_id, Sighting.weather_conditions.is_(None))
                    .values(weather_conditions=text)
                )
                if done.rowcount == 0:
                    return
                sighting, has_image = (
                    await db.execute(
                        select(Sighting, HAS_IMAGE).options(SKIP_IMAGE).where(Sighting.id == sighting_id)
                    )
                ).one()
                body = sighting_response(sighting, has_image=bool(has_image))
        logger.info("sighting %d weather: %s", sighting_id, text)
        sighting_hub.publish(
            SightingUpdated(sighting_id=sighting_id, device_id=body.device_id, payload=asdict(body))
        )
    except LookupFailed as exc:
        logger.warning("Weather lookup failed for sighting %d: %s", sighting_id, exc)
    except Exception:
        logger.exception("Weather fill failed for sighting %d", sighting_id)


async def schedule_weather(sighting_id: int) -> None:
    """Start ``fill_weather`` without waiting for it.

    Litestar runs this as a response background task, so it starts once the
    request transaction has committed and the 201 has gone to the Pi. The task
    then reads a row that is really there.
    """
    if not settings.WEATHER_ENABLED:
        return
    asyncio.create_task(fill_weather(sighting_id))
