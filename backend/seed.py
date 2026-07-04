"""Seed the database with demo data matching the web app's design fixtures.

Run from the repo root:

    python -m backend.seed

Uses ``settings.DATABASE_URL`` (PostgreSQL by default). For a quick local run
without Docker you can point it at SQLite instead::

    DATABASE_URL="sqlite+aiosqlite:///./peck_deck.db" python -m backend.seed

Idempotent-ish: if the owner account already exists the script exits without
touching anything. Pass ``--force`` to seed anyway (may create duplicates).

Demo login: dom@peck.deck / peckdeck  (all seeded users share that password).
"""
import asyncio
import json
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone

from .auth.jwt_utils import hash_password
from .config import settings
from .database.connection import create_tables, get_session_factory, init_db
from .database.models import Device, DeviceUser, Sighting, Species, User

DEMO_PASSWORD = "peckdeck"

USERS = [
    {"name": "Dominic Norris", "email": "dom@peck.deck", "role": "owner",
     "phone": "+1 (802) 555-0142", "notify_email": True, "notify_sms": True},
    {"name": "Margaret Norris", "email": "meg@peck.deck", "role": "viewer",
     "phone": "+1 (802) 555-0119", "notify_email": True, "notify_sms": False},
    {"name": "Theo Cole", "email": "theo@cole.studio", "role": "viewer",
     "phone": None, "notify_email": True, "notify_sms": False},
    {"name": "Pat Halloran", "email": "pat.h@audubon.local", "role": "viewer",
     "phone": "+1 (802) 555-0188", "notify_email": False, "notify_sms": True},
]

SPECIES = [
    ("Northern Cardinal", "Cardinalis cardinalis", "Passeriformes",
     ["#b8412c", "#5a1810", "#e5b89c"], "songbird",
     "https://en.wikipedia.org/wiki/Northern_cardinal",
     "Year-round resident. Males vivid red with black mask; females buff-brown with red wash. Frequent feeder visitor."),
    ("Black-capped Chickadee", "Poecile atricapillus", "Passeriformes",
     ["#1c2620", "#d4cdb8", "#7a6f5a"], "tit",
     "https://en.wikipedia.org/wiki/Black-capped_chickadee",
     "Tiny, curious. Black cap and bib, white cheeks. Often the first to find a new feeder."),
    ("American Goldfinch", "Spinus tristis", "Passeriformes",
     ["#d4a23a", "#1c1810", "#8a6f1f"], "finch",
     "https://en.wikipedia.org/wiki/American_goldfinch",
     "Brilliant yellow in summer; olive-buff in winter. Strict vegetarian — loves nyjer and sunflower hearts."),
    ("Tufted Titmouse", "Baeolophus bicolor", "Passeriformes",
     ["#7a8a8c", "#2a3032", "#d4cdb8"], "tit",
     "https://en.wikipedia.org/wiki/Tufted_titmouse",
     "Slate-gray crested songbird with rusty flanks. Acrobatic; takes one seed at a time."),
    ("House Finch", "Haemorhous mexicanus", "Passeriformes",
     ["#bf6952", "#5e3530", "#d8c2a8"], "finch",
     "https://en.wikipedia.org/wiki/House_finch",
     "Males raspberry-red on head and breast. Originally Western; now coast to coast."),
    ("Blue Jay", "Cyanocitta cristata", "Passeriformes",
     ["#3f6e89", "#15263a", "#d4cdb8"], "jay",
     "https://en.wikipedia.org/wiki/Blue_jay",
     "Loud, intelligent, bossy. Crested with vivid blue back, white underparts, black necklace."),
    ("Downy Woodpecker", "Dryobates pubescens", "Piciformes",
     ["#1c2620", "#ece4d2", "#b8412c"], "woodpecker",
     "https://en.wikipedia.org/wiki/Downy_woodpecker",
     "Smallest North American woodpecker. Black and white checkered; males with red nape patch."),
    ("Mourning Dove", "Zenaida macroura", "Columbiformes",
     ["#a89d80", "#5a4f3f", "#d4cdb8"], "dove",
     "https://en.wikipedia.org/wiki/Mourning_dove",
     "Slim, long-tailed; soft mournful coo. Ground-feeder beneath the tray."),
    ("White-breasted Nuthatch", "Sitta carolinensis", "Passeriformes",
     ["#5a6a78", "#1c2028", "#ece4d2"], "nuthatch",
     "https://en.wikipedia.org/wiki/White-breasted_nuthatch",
     "Walks down trunks headfirst. Slate above, white below, black cap."),
    ("Carolina Wren", "Thryothorus ludovicianus", "Passeriformes",
     ["#a86530", "#52301a", "#e5d4b8"], "wren",
     "https://en.wikipedia.org/wiki/Carolina_wren",
     "Bold rusty-brown wren with white eyebrow. Loud teakettle song."),
    ("Red-bellied Woodpecker", "Melanerpes carolinus", "Piciformes",
     ["#b8412c", "#1c2620", "#e5d4b8"], "woodpecker",
     "https://en.wikipedia.org/wiki/Red-bellied_woodpecker",
     "Zebra-backed, with a red cap (males) or nape (females). Pale belly tinged red."),
    ("Dark-eyed Junco", "Junco hyemalis", "Passeriformes",
     ["#4a4a4a", "#222222", "#ece4d2"], "sparrow",
     "https://en.wikipedia.org/wiki/Dark-eyed_junco",
     "Slate above, white belly. Ground-feeder; nicknamed 'snowbird' for winter arrivals."),
]

DEVICES = [
    {"name": "Backyard Maple", "city": "Burlington", "state": "VT",
     "classification_tier": "auto", "feed_type": "Black-oil sunflower",
     "battery": 0.78, "signal": "good", "last_seen_secs": 32, "weight": 5},
    {"name": "Front Porch", "city": "Burlington", "state": "VT",
     "classification_tier": "gpu", "feed_type": "Nyjer thistle",
     "battery": 0.42, "signal": "good", "last_seen_secs": 60, "weight": 3},
    {"name": "Cabin Window", "city": "Stowe", "state": "VT",
     "classification_tier": "local", "feed_type": "Suet cake",
     "battery": 0.18, "signal": "weak", "last_seen_secs": 14 * 60, "weight": 1},
]


def _hour_weight(hour: int) -> float:
    if 5 <= hour <= 9:
        return 4.0  # dawn rush
    if 15 <= hour <= 18:
        return 2.5  # afternoon
    if 10 <= hour <= 14:
        return 1.0
    return 0.05  # rare at night


async def seed() -> None:
    force = "--force" in sys.argv
    init_db(settings.DATABASE_URL)
    await create_tables()
    rng = random.Random(42)

    async with get_session_factory()() as db:
        async with db.begin():
            from sqlalchemy import select

            existing = await db.execute(
                select(User).where(User.email == USERS[0]["email"])
            )
            if existing.scalar_one_or_none() is not None and not force:
                print("Owner account already exists — skipping seed (use --force).")
                return

            # ── Users ────────────────────────────────────────────────────────
            users = []
            for u in USERS:
                user = User(
                    name=u["name"], email=u["email"],
                    password_hash=hash_password(DEMO_PASSWORD),
                    phone=u["phone"], role=u["role"],
                    notify_email=u["notify_email"], notify_sms=u["notify_sms"],
                )
                db.add(user)
                users.append(user)
            await db.flush()
            owner = users[0]

            # ── Species ──────────────────────────────────────────────────────
            species_objs = []
            for common, sci, order, palette, silhouette, wiki, note in SPECIES:
                genus, _, species_name = sci.partition(" ")
                sp = Species(
                    common_name=common, genus=genus, species_name=species_name,
                    order_name=order, wiki_url=wiki,
                    palette=json.dumps(palette), silhouette=silhouette, note=note,
                )
                db.add(sp)
                species_objs.append(sp)
            await db.flush()

            # ── Devices (all owned by Dominic; shared with the viewers) ───────
            now = datetime.now(timezone.utc)
            device_objs = []
            for d in DEVICES:
                dev = Device(
                    name=d["name"], city=d["city"], state=d["state"],
                    owner_id=owner.id, classification_tier=d["classification_tier"],
                    feed_type=d["feed_type"], token=secrets.token_urlsafe(32),
                    battery=d["battery"], signal=d["signal"],
                    last_seen=now - timedelta(seconds=d["last_seen_secs"]),
                )
                db.add(dev)
                device_objs.append(dev)
            await db.flush()
            for viewer in users[1:]:
                for dev in device_objs:
                    db.add(DeviceUser(device_id=dev.id, user_id=viewer.id))

            # ── Sightings across the last 7 days ─────────────────────────────
            # Cardinal/chickadee weighted heaviest so "most frequent" is stable.
            species_weights = [8, 6, 5, 4, 4, 3, 3, 3, 2, 2, 2]
            device_weights = [d["weight"] for d in DEVICES]
            tiers = ["gpu", "local", "cloud"]
            tier_weights = [5, 4, 1]

            total = 0
            for day_offset in range(6, -1, -1):
                day = now - timedelta(days=day_offset)
                n = rng.randint(16, 26)
                for _ in range(n):
                    hour = rng.choices(range(24), weights=[_hour_weight(h) for h in range(24)])[0]
                    ts = day.replace(
                        hour=hour, minute=rng.randint(0, 59),
                        second=rng.randint(0, 59), microsecond=0,
                    )
                    if ts > now:
                        continue
                    sp = rng.choices(species_objs, weights=species_weights)[0]
                    dev = rng.choices(device_objs, weights=device_weights)[0]
                    tier = rng.choices(tiers, weights=tier_weights)[0]
                    conf = round(rng.uniform(0.68, 0.99), 2)
                    db.add(Sighting(
                        species_id=sp.id, device_id=dev.id, datetime=ts,
                        classification_tier_used=tier, confidence_score=conf,
                        delayed=False,
                    ))
                    total += 1

    print(f"Seeded {len(USERS)} users, {len(SPECIES)} species, "
          f"{len(DEVICES)} devices, {total} sightings.")
    print(f"Login: {USERS[0]['email']} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
