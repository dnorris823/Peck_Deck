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
from datetime import datetime, timedelta, timezone

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
        password_hash=hash_password(OWNER_PASSWORD), phone="+15550001",
        role="owner", notify_email=True, notify_sms=True,
    )
    viewer = User(
        name="Viewer Two", email="viewer@test.dev",
        password_hash=hash_password(VIEWER_PASSWORD), phone=None,
        role="viewer", notify_email=True, notify_sms=False,
    )
    db.add_all([owner, viewer])
    await db.flush()

    spA = _species("Test Cardinal", "Cardinalis", "testus", ["#b8412c", "#5a1810", "#e5b89c"])
    spB = _species("Test Jay", "Cyanocitta", "testus", ["#3f6e89", "#15263a", "#d4cdb8"])
    spC = _species("Test Wren", "Thryothorus", "testus", ["#a86530", "#52301a", "#e5d4b8"])
    db.add_all([spA, spB, spC])
    await db.flush()

    dev1 = Device(name="Dev One", city="Burlington", state="VT", owner_id=owner.id,
                  classification_tier="auto", feed_type="sunflower", token=DEV1_TOKEN,
                  battery=0.8, signal="good", last_seen=now)                       # online
    dev2 = Device(name="Dev Two", city="Stowe", state="VT", owner_id=owner.id,
                  classification_tier="gpu", feed_type="nyjer", token=DEV2_TOKEN,
                  battery=0.5, signal="good", last_seen=now - timedelta(minutes=40))  # offline
    dev3 = Device(name="Dev Three", city="Essex", state="VT", owner_id=owner.id,
                  classification_tier="local", feed_type="suet", token=DEV3_TOKEN,
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
