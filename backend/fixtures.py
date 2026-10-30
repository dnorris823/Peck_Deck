"""Reusable, deterministic demo dataset for tests and local/CI runs.

This is the single source of truth for the small, fully-deterministic dataset
the suite asserts against. It is intentionally separate from :mod:`backend.seed`
(which builds a larger, randomized dataset for the web-app demo): fixtures here
are small enough to assert *exact* counts and stable enough that the same code
seeds a throwaway SQLite file (unit tests) or a real ``postgres:16`` service
(integration tests).

Usage::

    from backend.database.connection import get_session_factory
    from backend.fixtures import seed_reference_data

    async with get_session_factory()() as db:
        async with db.begin():
            ids = await seed_reference_data(db)

``ids`` maps friendly names (``owner_id``, ``dev1_id``, ``spA_id`` …) to the
primary keys the dataset produced. Device auth tokens are stable strings
(``dev1-token`` …) so tests can authenticate without a round-trip.
"""
import json
import secrets
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from .auth.jwt_utils import hash_password
from .database.models import Device, DeviceUser, Sighting, Species, User

# Stable device tokens the tests authenticate with.
DEV1_TOKEN = "dev1-token"
DEV2_TOKEN = "dev2-token"
DEV3_TOKEN = "dev3-token"

# Passwords for the two seeded accounts (bcrypt-hashed on insert).
OWNER_PASSWORD = "ownerpw"
VIEWER_PASSWORD = "viewerpw"


def _species(common: str, genus: str, sp: str, palette: list[str]) -> Species:
    return Species(
        common_name=common,
        genus=genus,
        species_name=sp,
        order_name="Passeriformes",
        wiki_url=f"https://en.wikipedia.org/wiki/{common.replace(' ', '_')}",
        palette=json.dumps(palette),
        silhouette="songbird",
        note=f"{common} note.",
    )


async def seed_reference_data(db: AsyncSession) -> dict:
    """Populate ``db`` with the canonical demo dataset and return its ids.

    The caller owns the transaction (wrap the call in ``async with db.begin()``).
    The dataset is deterministic: 2 users, 3 species, 3 devices (one online, one
    offline, one low-battery) and 6 sightings — 5 visible to the seeded owner,
    1 on an owner-only device that the viewer cannot see.
    """
    now = datetime.now(timezone.utc)

    owner = User(
        name="Owner One", email="owner@test.dev",
        password_hash=hash_password(OWNER_PASSWORD),
        role="owner", notify_email=True,
    )
    viewer = User(
        name="Viewer Two", email="viewer@test.dev",
        password_hash=hash_password(VIEWER_PASSWORD),
        role="viewer", notify_email=True,
    )
    db.add_all([owner, viewer])
    await db.flush()

    spA = _species("Test Cardinal", "Cardinalis", "testus", ["#b8412c", "#5a1810", "#e5b89c"])
    spB = _species("Test Jay", "Cyanocitta", "testus", ["#3f6e89", "#15263a", "#d4cdb8"])
    spC = _species("Test Wren", "Thryothorus", "testus", ["#a86530", "#52301a", "#e5d4b8"])
    db.add_all([spA, spB, spC])
    await db.flush()

    dev1 = Device(name="Dev One", city="Burlington", state="VT", owner_id=owner.id,
                  feed_type="sunflower", token=DEV1_TOKEN,
                  battery=0.8, signal="good", last_seen=now)                       # online
    dev2 = Device(name="Dev Two", city="Stowe", state="VT", owner_id=owner.id,
                  feed_type="nyjer", token=DEV2_TOKEN,
                  battery=0.5, signal="good", last_seen=now - timedelta(minutes=40))  # offline
    dev3 = Device(name="Dev Three", city="Essex", state="VT", owner_id=owner.id,
                  feed_type="suet", token=DEV3_TOKEN,
                  battery=0.15, signal="good", last_seen=now)                      # warn (low battery)
    db.add_all([dev1, dev2, dev3])
    await db.flush()

    # viewer can access dev1 only (membership, not ownership)
    db.add(DeviceUser(device_id=dev1.id, user_id=viewer.id))

    def sighting(sp, dev, when, conf, tier):
        return Sighting(species_id=sp.id, device_id=dev.id, datetime=when,
                        confidence_score=conf, classification_tier_used=tier, delayed=False)

    three_days_ago = now - timedelta(days=3)
    db.add_all([
        sighting(spA, dev1, now, 0.95, "gpu"),
        sighting(spA, dev1, now, 0.90, "local"),
        sighting(spA, dev1, now, 0.88, "gpu"),
        sighting(spB, dev1, now, 0.80, "local"),
        sighting(spB, dev1, now, 0.75, "local"),
        sighting(spA, dev2, three_days_ago, 0.70, "cloud"),  # not visible to viewer
    ])
    await db.flush()

    return {
        "owner_id": owner.id, "viewer_id": viewer.id,
        "dev1_id": dev1.id, "dev2_id": dev2.id, "dev3_id": dev3.id,
        "spA_id": spA.id, "spB_id": spB.id, "spC_id": spC.id,
    }


# The zone the local-hour fixture lives in.
HOUR_STATION_TZ = "America/Los_Angeles"


async def seed_hour_station(db: AsyncSession, species_ids: tuple[int, int]) -> dict:
    """A throwaway user and device with visits at known local times.

    The visits are at fixed Los Angeles wall-clock times, so the local-hour
    stats can be asserted exactly. A 19:05 visit in Los Angeles is hour 2 or 3
    in UTC, which is the bug the local-hour routes exist to avoid. Nobody else
    can see this device, so the seeded owner's exact counts still hold.

    ``species_ids`` is ``(a, b)``. Species a gets four visits, one of them 60
    days ago. Species b gets one. The caller owns the transaction.
    """
    zone = ZoneInfo(HOUR_STATION_TZ)
    today = datetime.now(zone).date()

    def local(days_ago: int, hh: int, mm: int) -> datetime:
        wall = datetime.combine(today - timedelta(days=days_ago), time(hh, mm), tzinfo=zone)
        # UTC on the way in: SQLite drops the offset and the reader assumes UTC.
        return wall.astimezone(timezone.utc)

    user = User(
        name="Hour Station", email=f"hours_{secrets.token_hex(4)}@test.dev",
        password_hash="x", role="viewer", notify_email=False,
    )
    db.add(user)
    await db.flush()
    device = Device(name="Hour Device", owner_id=user.id, token=secrets.token_urlsafe(12))
    db.add(device)
    await db.flush()

    sp_a, sp_b = species_ids
    visits = {
        "a_evening_1": (sp_a, local(2, 19, 5)),
        "a_evening_2": (sp_a, local(3, 19, 40)),
        "a_morning": (sp_a, local(4, 8, 10)),
        "a_old": (sp_a, local(60, 12, 0)),     # outside the 30-day window
        "b_dawn": (sp_b, local(1, 6, 30)),
    }
    for sp_id, when in visits.values():
        db.add(Sighting(species_id=sp_id, device_id=device.id, datetime=when,
                        confidence_score=0.9, classification_tier_used="gpu", delayed=False))
    await db.flush()
    return {"user_id": user.id, "device_id": device.id,
            **{name: when for name, (_sp, when) in visits.items()}}
