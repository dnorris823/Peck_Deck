"""Virtual feeder — the device simulator (FLEDGE Phase 5, "Decoy").

Stands in for the Raspberry Pi so the whole pipeline can be watched without any
hardware: it authenticates with a device token and posts realistic sightings to
``POST /sightings``, driving classification tiers, the gallery, the dashboard
aggregates, device "online" status and the notification fan-out for real.

**It uses the Pi's own client.** ``raspberry_pi_code.api_client.BackendClient``
is imported and driven unmodified, so the multipart shape on the wire is exactly
what the hardware will send — the same seam the Phase 3 contract tests pin. If
the simulator works, the Pi's upload path works; there is no second
implementation to drift.

Run it from the repo root against a running stack::

    # Backfill 120 sightings over the last 14 days, then stop
    python -m backend.simulator --mode burst --count 120 --days 14

    # Live drip — one sighting every ~8s until Ctrl-C
    python -m backend.simulator --mode live --interval 8

With no ``--device-token`` it signs in as the demo owner and reads the tokens
straight off ``GET /devices``, so a seeded stack needs zero configuration.
Sightings are spread across every device it finds.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import random
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("peckdeck.simulator")

REPO_ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_CSV = REPO_ROOT / "machine_learning" / "taxonomy.csv"

DEFAULT_API_URL = os.getenv("PECK_API_URL", "http://localhost:8000")
DEFAULT_OWNER_EMAIL = os.getenv("PECK_DEMO_EMAIL", "dom@peck.deck")
DEFAULT_OWNER_PASSWORD = os.getenv("PECK_DEMO_PASSWORD", "peckdeck")

# Which tier handled a visit, and how confident that tier tends to be. Mirrors
# the real fallback chain: Tier 1 runs on every capture and is the weakest, so
# it is common but often escalates; Tier 2 handles most escalations; Tier 3
# (Claude) is the rare last resort and, being the most capable, the most
# confident. Weights match backend/seed.py so simulated and seeded data agree.
TIER_PROFILE: dict[str, tuple[float, tuple[float, float]]] = {
    "local": (4.0, (0.55, 0.88)),
    "gpu": (5.0, (0.72, 0.97)),
    "cloud": (1.0, (0.80, 0.99)),
}

# Palettes for the species that the seed dataset doesn't already carry, so a
# simulator-created species still renders a distinct plate in the gallery.
_FALLBACK_PALETTES = [
    ["#b8412c", "#5a1810", "#e5b89c"], ["#3f6e89", "#15263a", "#d4cdb8"],
    ["#d4a23a", "#1c1810", "#8a6f1f"], ["#2d4a36", "#1d3225", "#d4cdb8"],
    ["#a86530", "#52301a", "#e5d4b8"], ["#6b4570", "#2a1a2e", "#e2d8c1"],
    ["#7a8a8c", "#2a3032", "#ece4d2"], ["#a89d80", "#5a4f3f", "#d4cdb8"],
]


# ── Visit modelling ──────────────────────────────────────────────────────────
def hour_weight(hour: int) -> float:
    """Relative likelihood of a feeder visit at a given local hour.

    Birds feed hardest at dawn and again before roosting; almost nothing visits
    a seed feeder overnight. Kept identical to ``backend.seed`` so the simulated
    hour-of-day histogram is continuous with the seeded one rather than showing
    a visible seam where one dataset ends and the other begins.
    """
    if 5 <= hour <= 9:
        return 4.0     # dawn rush
    if 15 <= hour <= 18:
        return 2.5     # afternoon
    if 10 <= hour <= 14:
        return 1.0
    return 0.05        # rare at night


@dataclass(frozen=True)
class SpeciesEntry:
    common_name: str
    scientific_name: str
    palette: list[str]


def load_species(csv_path: Path = TAXONOMY_CSV) -> list[SpeciesEntry]:
    """Read the Tier 1 model's own taxonomy so simulated species are real ones.

    ``machine_learning/taxonomy.csv`` maps model output indices to names, which
    makes it the right source: every species the simulator can produce is a
    species the on-device model could actually predict.
    """
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{csv_path} has no rows")
    return [
        SpeciesEntry(
            common_name=row["common_name"].strip(),
            scientific_name=f"{row['genus'].strip()} {row['species'].strip()}",
            palette=_FALLBACK_PALETTES[i % len(_FALLBACK_PALETTES)],
        )
        for i, row in enumerate(rows)
    ]


def species_weights(count: int) -> list[float]:
    """A long tail: a few regulars dominate, rare visitors stay rare.

    A uniform draw would give twenty equally-common species, which reads as
    obviously fake on the dashboard — real feeder data is dominated by three or
    four birds. 1/(rank+1) gets that shape in one line.
    """
    return [1.0 / (i + 1) for i in range(count)]


def pick_tier(rng: random.Random) -> tuple[str, float]:
    """Choose a classification tier and a plausible confidence for it."""
    tiers = list(TIER_PROFILE)
    weights = [TIER_PROFILE[t][0] for t in tiers]
    tier = rng.choices(tiers, weights=weights)[0]
    low, high = TIER_PROFILE[tier][1]
    return tier, round(rng.uniform(low, high), 2)


def backfill_timestamps(
    rng: random.Random, count: int, days: int, *, now: datetime | None = None
) -> list[datetime]:
    """``count`` timestamps over the last ``days``, day/night weighted, ascending.

    Never returns a future timestamp: today is only partially elapsed, so an
    hour drawn from the full 24 has to be rejected if it hasn't happened yet.
    """
    now = now or datetime.now(timezone.utc)
    hours = list(range(24))
    weights = [hour_weight(h) for h in hours]
    stamps: list[datetime] = []
    # Bounded retries: near midnight almost every draw for "today" is in the
    # future, so a naive while-loop could spin.
    for _ in range(count * 20):
        if len(stamps) >= count:
            break
        day = now - timedelta(days=rng.randint(0, max(0, days - 1)))
        ts = day.replace(
            hour=rng.choices(hours, weights=weights)[0],
            minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0,
        )
        if ts <= now:
            stamps.append(ts)
    return sorted(stamps)


# ── Wire layer — the real Pi client ──────────────────────────────────────────
def _backend_client_cls():
    """Import the Pi's client lazily, with a message that says where to run from.

    ``raspberry_pi_code`` is a sibling package, not a backend dependency (and it
    is deliberately absent from the API container image), so this fails for
    anyone running the simulator from somewhere other than a repo checkout.
    """
    try:
        from raspberry_pi_code.api_client import BackendClient
    except ImportError as exc:
        raise SystemExit(
            "Could not import raspberry_pi_code.api_client — the simulator drives "
            "the Pi's real client so it exercises the exact upload contract.\n"
            "Run it from the repo root:  python -m backend.simulator"
        ) from exc
    return BackendClient


async def _http_json(session, method: str, url: str, **kwargs):
    async with session.request(method, url, **kwargs) as resp:
        resp.raise_for_status()
        return await resp.json()


async def discover_devices(
    api_url: str, email: str, password: str
) -> list[tuple[int, str, str]]:
    """Sign in as a user and read every visible device's ``(id, name, token)``.

    ``GET /devices`` returns the device token — it is what the Devices screen
    shows for provisioning a Pi — so the simulator can bootstrap itself against
    a seeded stack with no configuration at all.
    """
    import aiohttp

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20)
    ) as session:
        auth = await _http_json(
            session, "POST", f"{api_url}/login",
            json={"email": email, "password": password},
        )
        devices = await _http_json(
            session, "GET", f"{api_url}/devices",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
    return [(d["id"], d["name"], d["token"]) for d in devices if d.get("token")]


class VirtualFeeder:
    """One simulated station: a device token plus the visits it invents."""

    def __init__(
        self,
        api_url: str,
        device_token: str,
        device_name: str,
        species: list[SpeciesEntry],
        rng: random.Random,
        image_dir: Path,
    ) -> None:
        self.name = device_name
        self._client = _backend_client_cls()(api_url, device_token)
        self._species = species
        self._weights = species_weights(len(species))
        self._rng = rng
        self._image_dir = image_dir

    def _image_for(self, entry: SpeciesEntry) -> Path:
        """Write (once) the placeholder plate for a species and return its path.

        The Pi's client takes an ``image_path`` and streams the file — that is
        the contract being exercised, so the simulator really does put bytes on
        disk rather than reaching around the client with an in-memory buffer.
        """
        from .demo_images import plate_for

        path = self._image_dir / f"{entry.common_name.replace(' ', '_')}.jpg"
        if not path.exists():
            path.write_bytes(plate_for(entry.palette))
        return path

    async def visit(self, when: datetime, *, delayed: bool = False) -> bool:
        """Invent one visit and upload it. Returns True on success."""
        entry = self._rng.choices(self._species, weights=self._weights)[0]
        tier, confidence = pick_tier(self._rng)
        ok = await self._client.post_sighting(
            image_path=self._image_for(entry),
            timestamp=when.isoformat(),
            common_name=entry.common_name,
            scientific_name=entry.scientific_name,
            confidence=confidence,
            tier_used=tier,
            delayed=delayed,
        )
        level = logging.INFO if ok else logging.WARNING
        logger.log(
            level, "%s %-14s %-26s %s %.2f",
            "✓" if ok else "✗", self.name, entry.common_name, tier, confidence,
        )
        return ok


# ── Modes ────────────────────────────────────────────────────────────────────
async def run_burst(
    feeders: list[VirtualFeeder], rng: random.Random, count: int, days: int
) -> int:
    """One-shot backfill: ``count`` sightings spread over the last ``days``."""
    stamps = backfill_timestamps(rng, count, days)
    logger.info(
        "burst: posting %d sightings across %d device(s) over %d day(s)",
        len(stamps), len(feeders), days,
    )
    posted = 0
    for ts in stamps:
        feeder = rng.choice(feeders)
        # Backdated captures are exactly what the offline-sync path uploads, so
        # marking them delayed keeps the history honest about how it arrived.
        if await feeder.visit(ts, delayed=True):
            posted += 1
    return posted


async def run_live(
    feeders: list[VirtualFeeder],
    rng: random.Random,
    interval: float,
    jitter: float,
    limit: int | None,
) -> int:
    """Live drip: a sighting every ``interval`` (±``jitter``) seconds until stopped."""
    logger.info(
        "live: one sighting every ~%.1fs across %d device(s) — Ctrl-C to stop",
        interval, len(feeders),
    )
    posted = 0
    consecutive_failures = 0
    while limit is None or posted < limit:
        feeder = rng.choice(feeders)
        if await feeder.visit(datetime.now(timezone.utc)):
            posted += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            # The loop counts *successes*, so without this a backend that has
            # gone away (or a revoked token) would spin here forever.
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "giving up after %d consecutive failed uploads — "
                    "is the backend still up, and is the device token valid?",
                    consecutive_failures,
                )
                break
        await asyncio.sleep(max(0.05, interval + rng.uniform(-jitter, jitter)))
    return posted


# ── CLI ──────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m backend.simulator",
        description="Virtual bird feeder — drives the real POST /sightings contract.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m backend.simulator --mode burst --count 120 --days 14\n"
            "  python -m backend.simulator --mode live --interval 5\n"
        ),
    )
    p.add_argument("--mode", choices=("live", "burst"), default="live",
                   help="live drip (default) or a one-shot history backfill")
    p.add_argument("--api-url", default=DEFAULT_API_URL,
                   help=f"backend base URL (default {DEFAULT_API_URL})")
    p.add_argument("--device-token", action="append", default=None, metavar="TOKEN",
                   help="device token; repeat for several. Omit to discover via login.")
    p.add_argument("--email", default=DEFAULT_OWNER_EMAIL,
                   help="account used to discover device tokens")
    p.add_argument("--password", default=DEFAULT_OWNER_PASSWORD,
                   help="password for --email")
    p.add_argument("--count", type=int, default=80,
                   help="burst mode: how many sightings (default 80)")
    p.add_argument("--days", type=int, default=7,
                   help="burst mode: spread over the last N days (default 7)")
    p.add_argument("--interval", type=float, default=8.0,
                   help="live mode: seconds between sightings (default 8)")
    p.add_argument("--jitter", type=float, default=3.0,
                   help="live mode: +/- seconds of randomness on the interval")
    p.add_argument("--limit", type=int, default=None,
                   help="live mode: stop after N sightings (default: run forever)")
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed — set it for a reproducible run")
    return p


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rng = random.Random(args.seed)
    species = load_species()
    api_url = args.api_url.rstrip("/")

    if args.device_token:
        devices = [(None, f"device-{i + 1}", t)
                   for i, t in enumerate(args.device_token)]
    else:
        logger.info("no --device-token given; discovering devices as %s", args.email)
        try:
            devices = await discover_devices(api_url, args.email, args.password)
        except Exception as exc:
            logger.error(
                "Could not discover devices at %s (%s).\n"
                "Is the stack up and seeded?  docker compose up  +  python -m backend.seed\n"
                "Or pass --device-token explicitly.",
                api_url, exc,
            )
            return 2
        if not devices:
            logger.error("Signed in, but %s has no devices to simulate.", args.email)
            return 2

    # Plates are regenerated per run rather than committed as binary assets;
    # a temp dir keeps them out of the working tree.
    with tempfile.TemporaryDirectory(prefix="peckdeck-sim-") as tmp:
        feeders = [
            VirtualFeeder(api_url, token, name, species, rng, Path(tmp))
            for _, name, token in devices
        ]
        logger.info("simulating %d device(s) against %s",
                    len(feeders), api_url)

        try:
            if args.mode == "burst":
                posted = await run_burst(feeders, rng, args.count, args.days)
            else:
                posted = await run_live(
                    feeders, rng, args.interval, args.jitter, args.limit
                )
        except asyncio.CancelledError:
            logger.info("stopped")
            return 0

    logger.info("posted %d sighting(s)", posted)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        # Ctrl-C during a live run is the normal way to stop, not a failure.
        print("\nstopped", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
