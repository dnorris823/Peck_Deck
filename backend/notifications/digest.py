"""The evening digest push and the weekly digest email.

Each user turns them on in Settings. Both default off.

- The evening push goes once a day at the user's ``digest_push_time``, default
  19:00 in their time zone. It counts the day from local midnight to the send:
  "Today: 23 birds, 7 species", then the new species line. A day with no birds
  sends nothing. Tapping it opens Home.
- The weekly email goes on Sunday from 08:00 local, through SendGrid. It covers
  the seven local days before Sunday. Per feeder it gives bird visits, species,
  the species new that week, and up to three photos. A photo is the
  highest-confidence Tier 2 sighting of one species, and the three come from the
  three highest-confidence species. A week with no birds sends nothing.

Rules that keep the numbers honest:

- Bird counts filter on ``is_bird_sighting()``. Animal visits get a line of
  their own and never add to the bird numbers.
- "Unknown" is a bird visit, because the camera decided it was a bird. It is not
  a species, since it names none.
- "New" comes from ``new_species.new_kinds()``, the rule the new species alerts
  use. The digest asks it about the first sighting of each species in the
  period. A sighting waiting for the Tier 2 re-check is skipped, because Tier 2
  may change its species. The digest ignores the user's alert switches, and
  keeps the first ever confidence floor.
- A user with no time zone counts in UTC. The web app sets the zone from the
  browser on the first visit to Settings.

One run a minute decides, per user and digest, whether a period is due. It
writes the send time and commits before it sends. A restart then finds the
period done and sends nothing twice. A send that fails is not retried. The empty
day is marked done as well, so a bird at 21:00 does not send a 19:00 push late.

``DIGESTS_ENABLED`` turns the task on. It runs in the API process, like the
hourly feed check in ``backend/feed/monitor.py``.
"""
import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..database.connection import get_session_factory
from ..database.models import Device, Sighting, Species, User, UserPreferences
from ..devices.operations import as_utc
from ..sightings.operations import _accessible_device_ids
from ..species.operations import ANIMAL, is_bird_sighting
from . import new_species
from .email_sender import send_email
from .push import delete_endpoints, subscriptions_for_users, to_target
from .push_sender import push_enabled, send_push

logger = logging.getLogger("peckdeck.digest")

RUN_INTERVAL_SECONDS = 60
# The weekly email: Sunday, from 08:00 local.
EMAIL_WEEKDAY = 6
EMAIL_TIME = time(8, 0)
DEFAULT_PUSH_TIME = "19:00"
BEST_PHOTOS = 3
TIER2 = "gpu"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_PENDING = "pending"

# The words for each kind of new, in the push and the email.
PUSH_LABEL = {
    new_species.FIRST_EVER: "New for Peck Deck",
    new_species.FIRST_THIS_YEAR: "New this year",
}
EMAIL_LABEL = {
    new_species.FIRST_EVER: "first ever",
    new_species.FIRST_AT_FEEDER: "new at this feeder",
    new_species.FIRST_THIS_YEAR: "first this year",
}

_task: asyncio.Task | None = None


def parse_time(value: str) -> time | None:
    """``"19:00"`` as a time, or None when it is not HH:MM."""
    match = _TIME_RE.match(value or "")
    return time(int(match[1]), int(match[2])) if match else None


def user_zone(prefs: UserPreferences) -> ZoneInfo:
    try:
        return ZoneInfo(prefs.time_zone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz).astimezone(timezone.utc)


def _done(sent_at: datetime | None, today: date, tz: ZoneInfo) -> bool:
    return sent_at is not None and as_utc(sent_at).astimezone(tz).date() >= today


def push_window(prefs: UserPreferences, now: datetime) -> tuple[datetime, datetime] | None:
    """The day the evening push sums up, as UTC (start, end), or None when not due."""
    tz = user_zone(prefs)
    local = now.astimezone(tz)
    at = parse_time(prefs.digest_push_time) or parse_time(DEFAULT_PUSH_TIME)
    if local.time() < at or _done(prefs.digest_push_sent_at, local.date(), tz):
        return None
    return _midnight(local.date(), tz), now


def email_window(prefs: UserPreferences, now: datetime) -> tuple[datetime, datetime] | None:
    """The week the email sums up, as UTC (start, end), or None when not due.

    The seven local days before this Sunday. Midnight to midnight in the user's
    zone, so a week across a clock change is 167 or 169 hours.
    """
    tz = user_zone(prefs)
    local = now.astimezone(tz)
    if local.weekday() != EMAIL_WEEKDAY or local.time() < EMAIL_TIME:
        return None
    if _done(prefs.digest_email_sent_at, local.date(), tz):
        return None
    return _midnight(local.date() - timedelta(days=7), tz), _midnight(local.date(), tz)


# --- Counting ---

def _named_bird():
    """Bird sightings that name a species. "Unknown" is a visit, not a species."""
    return (
        is_bird_sighting(),
        Sighting.classification_tier_used != "none",
        Sighting.species_id.in_(
            select(Species.id).where(func.lower(func.trim(Species.common_name)) != "unknown")
        ),
    )


def _is_animal():
    return Sighting.species_id.in_(select(Species.id).where(Species.kind == ANIMAL))


def _in(devices: list[int], start: datetime, end: datetime):
    return (Sighting.device_id.in_(devices), Sighting.datetime >= start, Sighting.datetime < end)


async def _count(db: AsyncSession, *where, distinct_species: bool = False) -> int:
    what = func.count(func.distinct(Sighting.species_id)) if distinct_species else func.count()
    return (await db.execute(select(what).select_from(Sighting).where(*where))).scalar_one()


async def _new_in(
    db: AsyncSession, user_id: int, devices: list[int], start: datetime, end: datetime,
    *, kinds: tuple[str, ...] = tuple(EMAIL_LABEL),
) -> list[tuple[str, str]]:
    """(species name, strongest kind) for each species new in the window.

    Asks ``new_kinds`` about the first sighting of each species in the window.
    Only ``kinds`` count.
    """
    first = select(func.min(Sighting.id)).where(*_in(devices, start, end), *_named_bird())
    if new_species.recheck_on():
        first = first.where(
            or_(Sighting.tier2_recheck.is_(None), Sighting.tier2_recheck != _PENDING)
        )
    ids = list((await db.execute(first.group_by(Sighting.species_id))).scalars())
    if not ids:
        return []
    rows = (
        await db.execute(
            select(Sighting, Species)
            .join(Species, Species.id == Sighting.species_id)
            .options(defer(Sighting.image_data), defer(Sighting.thumbnail_data))
            .where(Sighting.id.in_(ids))
            .order_by(Sighting.id)
        )
    ).all()
    found = []
    for sighting, species in rows:
        applies = [
            k for k in await new_species.new_kinds(db, sighting, species, user_id) if k in kinds
        ]
        kind = new_species.pick(applies, None, sighting.confidence_score)
        if kind is not None:
            found.append((species.common_name, kind))
    return found


@dataclass
class DaySummary:
    birds: int
    species: int
    animals: int
    new: list[tuple[str, str]] = field(default_factory=list)


async def day_summary(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> DaySummary:
    """Every feeder the user can see, from ``start`` to ``end``."""
    devices = await _accessible_device_ids(db, user_id)
    window = _in(devices, start, end)
    birds = await _count(db, *window, is_bird_sighting())
    if not birds:
        return DaySummary(0, 0, await _count(db, *window, _is_animal()))
    # "First at this feeder" is about one feeder. The push sums up all of them.
    new = await _new_in(db, user_id, devices, start, end, kinds=tuple(PUSH_LABEL))
    return DaySummary(
        birds=birds,
        species=await _count(db, *window, *_named_bird(), distinct_species=True),
        animals=await _count(db, *window, _is_animal()),
        new=new,
    )


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def push_payload(summary: DaySummary) -> dict:
    title = f"Today: {_plural(summary.birds, 'bird')}, {_plural(summary.species, 'species', 'species')}"
    lines = []
    for kind, label in PUSH_LABEL.items():
        names = [name for name, k in summary.new if k == kind]
        if names:
            lines.append(f"{label}: {', '.join(names)}.")
    if summary.animals:
        lines.append(f"Also {_plural(summary.animals, 'animal visit')}.")
    return {
        "title": title,
        "body": " ".join(lines) or "No new species today.",
        # One digest on the lock screen. Tomorrow's replaces today's.
        "tag": "peckdeck-digest",
        "data": {"url": "/"},
    }


@dataclass
class FeederWeek:
    device_id: int
    name: str
    birds: int
    species: int
    animals: int
    new: list[tuple[str, str]]
    # (content id, species name, confidence, JPEG bytes), best first.
    photos: list[tuple[str, str, float, bytes]]


async def _best_photos(
    db: AsyncSession, device_id: int, start: datetime, end: datetime
) -> list[tuple[str, str, float, bytes]]:
    """The highest-confidence Tier 2 sighting per species, the best three of them."""
    rows = (
        await db.execute(
            select(Sighting.id, Sighting.species_id, Sighting.confidence_score, Species.common_name)
            .join(Species, Species.id == Sighting.species_id)
            .where(
                *_in([device_id], start, end), *_named_bird(),
                Sighting.classification_tier_used == TIER2,
                Sighting.image_data.is_not(None),
            )
            .order_by(Sighting.confidence_score.desc(), Sighting.id)
        )
    ).all()
    best: dict[int, tuple] = {}
    for row in rows:
        best.setdefault(row.species_id, row)
    top = list(best.values())[:BEST_PHOTOS]
    photos = []
    for row in top:
        thumb, image = (
            await db.execute(
                select(Sighting.thumbnail_data, Sighting.image_data).where(Sighting.id == row.id)
            )
        ).one()
        photos.append((f"digest_{row.id}", row.common_name, row.confidence_score, thumb or image))
    return photos


async def week_summary(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> list[FeederWeek]:
    """One entry per feeder the user can see, in name order."""
    devices = await _accessible_device_ids(db, user_id)
    if not devices:
        return []
    feeders = (
        await db.execute(select(Device.id, Device.name).where(Device.id.in_(devices)).order_by(Device.name))
    ).all()
    weeks = []
    for device_id, name in feeders:
        window = _in([device_id], start, end)
        birds = await _count(db, *window, is_bird_sighting())
        weeks.append(FeederWeek(
            device_id=device_id,
            name=name,
            birds=birds,
            species=await _count(db, *window, *_named_bird(), distinct_species=True),
            animals=await _count(db, *window, _is_animal()),
            new=await _new_in(db, user_id, [device_id], start, end) if birds else [],
            photos=await _best_photos(db, device_id, start, end) if birds else [],
        ))
    return weeks


def email_html(weeks: list[FeederWeek], start: datetime, end: datetime, tz: ZoneInfo) -> str:
    first = start.astimezone(tz).date()
    last = (end.astimezone(tz) - timedelta(days=1)).date()
    parts = [
        "<html><body>",
        f"<h2>Your week at the feeders</h2><p>{first.day} {first:%b} to {last.day} {last:%b}</p>",
    ]
    for week in weeks:
        parts.append(f"<h3>{escape(week.name)}</h3>")
        if not week.birds:
            parts.append("<p>No bird visits this week.</p>")
        else:
            parts.append(
                f"<p>{_plural(week.birds, 'bird visit')}, "
                f"{_plural(week.species, 'species', 'species')}.</p>"
            )
        if week.new:
            names = ", ".join(f"{escape(n)} ({EMAIL_LABEL[k]})" for n, k in week.new)
            parts.append(f"<p>New this week: {names}</p>")
        if week.animals:
            parts.append(f"<p>Animal visits: {week.animals}</p>")
        for cid, name, confidence, _ in week.photos:
            parts.append(
                f"<figure style='display:inline-block;margin:0 8px 8px 0'>"
                f"<img src='cid:{cid}' alt='{escape(name)}' width='180' style='border-radius:8px'>"
                f"<figcaption>{escape(name)}, {confidence:.0%}</figcaption></figure>"
            )
    parts.append("</body></html>")
    return "".join(parts)


# --- The run ---

@dataclass
class Outgoing:
    user_id: int
    push: dict | None = None
    subs: list = field(default_factory=list)
    email: dict | None = None


async def _plan(db: AsyncSession, user_id: int, now: datetime) -> Outgoing | None:
    """Decide what this user gets now, and mark each due period done."""
    prefs = await db.get(UserPreferences, user_id)
    user = await db.get(User, user_id)
    if prefs is None or user is None:
        return None
    out = Outgoing(user_id)

    window = push_window(prefs, now) if prefs.digest_push and push_enabled() else None
    if window is not None:
        prefs.digest_push_sent_at = now
        summary = await day_summary(db, user_id, *window)
        if summary.birds:
            out.subs = (await subscriptions_for_users(db, {user_id})).get(user_id, [])
            if out.subs:
                out.push = push_payload(summary)

    window = email_window(prefs, now) if prefs.digest_email and user.email else None
    if window is not None:
        prefs.digest_email_sent_at = now
        weeks = await week_summary(db, user_id, *window)
        if any(w.birds for w in weeks):
            tz = user_zone(prefs)
            first = window[0].astimezone(tz).date()
            out.email = {
                "to_email": user.email,
                "subject": f"Peck Deck: your week from {first.day} {first:%b}",
                "html_body": email_html(weeks, *window, tz),
                "inline_images": [(cid, data) for w in weeks for cid, _, _, data in w.photos],
            }
    await db.flush()
    return out


async def _deliver(out: Outgoing) -> None:
    if out.email is not None:
        await send_email(**out.email)
    if out.push is None:
        return
    results = await asyncio.gather(
        *(send_push(to_target(sub), out.push) for sub in out.subs), return_exceptions=True
    )
    dead = []
    for sub, result in zip(out.subs, results):
        if isinstance(result, Exception):
            logger.warning("digest: push failed for user %d: %s", out.user_id, result)
        elif result.gone:
            dead.append(sub.endpoint)
    if dead:
        async with get_session_factory()() as db:
            async with db.begin():
                await delete_endpoints(db, dead)


async def run_once(now: datetime | None = None) -> list[Outgoing]:
    """Send every digest that is due. Return what went out."""
    now = now or datetime.now(timezone.utc)
    async with get_session_factory()() as db:
        user_ids = list(
            (
                await db.execute(
                    select(UserPreferences.user_id).where(
                        or_(UserPreferences.digest_push, UserPreferences.digest_email)
                    )
                )
            ).scalars()
        )
    sent = []
    for user_id in user_ids:
        try:
            async with get_session_factory()() as db:
                async with db.begin():
                    out = await _plan(db, user_id, now)
            # After the commit, so a restart mid-send never sends twice.
            if out is not None and (out.push or out.email):
                await _deliver(out)
                sent.append(out)
        except Exception:
            # One user's failure must not stop the others' digests.
            logger.exception("digest: failed for user %d", user_id)
    return sent


async def _loop() -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("digest: run failed")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)


def start(enabled: bool) -> None:
    global _task
    if not enabled:
        logger.info("digest: off (DIGESTS_ENABLED is false)")
        return
    logger.info("digest: on, checking for due digests each minute")
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
