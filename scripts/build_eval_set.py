#!/usr/bin/env python3
"""Assemble a field-realistic evaluation set from iNaturalist observations.

``validate_tier1.py`` scores both tiers on Wikipedia lead images and gets 20/20.
That number is real but it is an *upper bound*: an encyclopedia lead image is a
bird photographer's keeper shot — full frame, sharp, side-on, well lit. A feeder
camera sees a bird at a third of frame, half behind a perch, mid-wingbeat, in
whatever light dawn offers. Those are different problems.

This pulls the second kind: research-grade iNaturalist observations, which are
photographs taken by amateurs in the field with phones and superzooms, and are
therefore much closer to the distribution the Pi actually meets.

Two choices worth knowing about:

* **Observations are filtered to on-or-after ``--since`` (default 2022-01-01).**
  Tier 2 is fine-tuned on iNat21, so iNaturalist photos are potentially its
  *training data* — scoring a model on what it memorised measures nothing. The
  iNat21 dataset was collected through 2021, so a later cutoff keeps the test
  set honest for Tier 2 as well as Tier 1. The cutoff is recorded in the
  manifest so the claim stays auditable.
* **At most one photo per observer per species.** One enthusiast's fifteen
  photos of the same individual at the same feeder is one sample dressed up as
  fifteen, and it would quietly weight the score toward whoever uploads most.
* **Photos are sampled at random from the whole pool**, seeded so a rerun picks
  the same ones. Any sort order is a bias: newest-first oversamples casual phone
  uploads, most-faved oversamples prize-winning portraits — which is the very
  bias this set exists to escape.

Ground truth is ``machine_learning/feeder_species.csv`` — the same 20 species
``validate_tier1.py`` uses, so the clean and field numbers are comparable.

    python scripts/build_eval_set.py                      # 15 photos/species
    python scripts/build_eval_set.py --per-species 30
    python scripts/build_eval_set.py --species "Cardinalis cardinalis"

Photos land in ``<root>/clean/<Genus_species>/obs_<id>.jpg`` alongside a
``manifest.json`` carrying licence and attribution for every file. The tree is
gitignored: these are other people's photographs under CC terms, cached for
local measurement, not project assets to redistribute.
"""

import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FEEDER_CSV = REPO_ROOT / "machine_learning" / "feeder_species.csv"
DEFAULT_ROOT = REPO_ROOT / ".eval_photos"

API = "https://api.inaturalist.org/v1"
# iNaturalist asks for an identifying User-Agent and tolerates ~60 requests/min.
UA = {"User-Agent": "PeckDeck-eval-set/1.0 (https://github.com/dnorris823/Peck_Deck)"}
API_PAUSE = 1.1
PHOTO_PAUSE = 0.4

# Licences that permit caching and redistribution of the derived measurement.
# `all rights reserved` photos are excluded outright.
LICENSES = "cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nc-sa"


def _get(url: str, timeout: int = 60) -> bytes:
    """GET with backoff on 429/5xx. The photo CDN throttles bursts."""
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or 2.0 * (2**attempt)
            time.sleep(min(wait, 30))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(2.0 * (2**attempt))
    raise RuntimeError("unreachable")


def _get_json(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    data = json.loads(_get(url))
    time.sleep(API_PAUSE)
    return data


def resolve_taxon(scientific: str) -> int | None:
    """Scientific name -> iNaturalist taxon id.

    Queried by name rather than trusting a hard-coded id table: ids are stable
    but a typo in the CSV should fail loudly here, not silently collect photos
    of the wrong bird.
    """
    data = _get_json("taxa", q=scientific, rank="species", per_page=5)
    for result in data.get("results", []):
        if result.get("name", "").lower() == scientific.lower():
            return int(result["id"])
    return None


def photo_url(photo: dict, size: str = "large") -> str | None:
    """iNat photo URLs are templated by size: .../square.jpg -> .../large.jpg."""
    url = photo.get("url")
    if not url:
        return None
    for known in ("square", "thumb", "small", "medium", "large", "original"):
        if f"/{known}." in url:
            return url.replace(f"/{known}.", f"/{size}.")
    return url


def _is_photo_shaped(photo: dict) -> bool:
    """Reject phone screenshots and panoramas by aspect ratio.

    The first sample this script ever pulled was a screenshot of a phone playing
    a security-camera clip: a tall black frame of app chrome with a cardinal in a
    letterboxed strip. That is not a hard *bird* photo, it is a hard *screenshot
    parsing* problem, and scoring the feeder camera on it measures the wrong
    thing. Real camera frames sit near 3:2, 4:3 or 16:9 (1.33-1.78); phone
    screenshots are ~2.17 the tall way. 2.2 splits them cleanly.
    """
    dims = photo.get("original_dimensions") or {}
    w, h = dims.get("width"), dims.get("height")
    if not w or not h:
        return True  # unknown shape — let the classifier have it
    ratio = max(w / h, h / w)
    return ratio <= 2.2


def collect_species(
    scientific: str,
    want: int,
    since: str,
    root: Path,
    offline: bool,
    rng: random.Random,
) -> list[dict]:
    """Fetch up to `want` distinct-observer photos for one species.

    Sampled at random from the whole research-grade pool rather than taken from
    the front of a sorted list. Newest-first oversamples casual phone uploads;
    most-faved oversamples prize-winning portraits, which is the Wikipedia bias
    this whole exercise exists to escape. Random is the only ordering that gives
    the distribution as it actually is.
    """
    slug = scientific.replace(" ", "_")
    out_dir = root / "clean" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    if offline:
        return [
            {"file": f"clean/{slug}/{p.name}", "scientific_name": scientific, "cached": True}
            for p in sorted(out_dir.glob("*.jpg"))
        ]

    taxon_id = resolve_taxon(scientific)
    if taxon_id is None:
        print(f"  {'SKIP':5} {scientific:28} no iNaturalist taxon match")
        return []

    query = dict(
        taxon_id=taxon_id,
        quality_grade="research",
        photos="true",
        photo_license=LICENSES,
        d1=since,
        locale="en",
    )

    # How deep does the pool go? iNat caps pagination at 10k results.
    head = _get_json("observations", per_page=1, **query)
    pool = min(int(head.get("total_results") or 0), 10_000)
    if pool == 0:
        print(f"  {'SKIP':5} {scientific:28} no matching observations")
        return []

    per_page = 30
    pages = list(range(1, (pool + per_page - 1) // per_page + 1))
    rng.shuffle(pages)

    records: list[dict] = []
    seen_observers: set[int] = set()
    rejected = 0

    # Cap per page so the sample spreads over several random slices. A single
    # page is 30 *consecutive* uploads — same week, often the same regional
    # push of migrants — so filling the quota from one page would correlate the
    # samples in exactly the way random paging was meant to avoid.
    per_page_cap = max(2, want // 4)

    for page in pages[:12]:
        if len(records) >= want:
            break
        data = _get_json("observations", per_page=per_page, page=page, **query)
        results = data.get("results", [])
        rng.shuffle(results)
        taken_here = 0

        for obs in results:
            if len(records) >= want or taken_here >= per_page_cap:
                break
            observer = (obs.get("user") or {}).get("id")
            if observer in seen_observers:
                continue
            photos = obs.get("photos") or []
            if not photos:
                continue
            if not _is_photo_shaped(photos[0]):
                rejected += 1
                continue
            url = photo_url(photos[0])
            if not url:
                continue

            target = out_dir / f"obs_{obs['id']}.jpg"
            if not target.exists():
                try:
                    target.write_bytes(_get(url))
                except Exception as exc:  # a single dead photo shouldn't end the run
                    print(f"  {'WARN':5} {scientific:28} photo {obs['id']}: {exc}")
                    continue
                time.sleep(PHOTO_PAUSE)

            seen_observers.add(observer)
            taken_here += 1
            records.append(
                {
                    "file": f"clean/{slug}/{target.name}",
                    "scientific_name": scientific,
                    "observation_id": obs["id"],
                    "observation_url": f"https://www.inaturalist.org/observations/{obs['id']}",
                    "observed_on": obs.get("observed_on"),
                    "license": photos[0].get("license_code"),
                    "attribution": photos[0].get("attribution"),
                    "photo_url": url,
                }
            )

    note = f" ({rejected} screenshot-shaped rejected)" if rejected else ""
    print(f"  {'OK':5} {scientific:28} {len(records):3d} photos of {pool} available{note}")
    return records


def load_species() -> list[str]:
    with open(FEEDER_CSV, newline="", encoding="utf-8") as fh:
        return [
            f"{r['genus'].strip()} {r['species'].strip()}" for r in csv.DictReader(fh)
        ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="output tree")
    ap.add_argument("--per-species", type=int, default=15)
    ap.add_argument(
        "--since",
        default="2022-01-01",
        help="only observations on/after this date — keeps the set clear of "
             "Tier 2's iNat21 training data",
    )
    ap.add_argument("--species", action="append",
                    help="limit to one scientific name (repeatable)")
    ap.add_argument("--seed", type=int, default=1,
                    help="sampling seed — same seed re-selects the same photos")
    ap.add_argument("--offline", action="store_true",
                    help="rebuild the manifest from already-downloaded photos")
    args = ap.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    species = args.species or load_species()
    print(f"Collecting <= {args.per_species} photos each for {len(species)} species "
          f"(observed on/after {args.since}, seed {args.seed})\n")

    records: list[dict] = []
    for scientific in species:
        # Per-species seed: adding a species later doesn't reshuffle the others.
        rng = random.Random(f"{args.seed}:{scientific}")
        records.extend(
            collect_species(
                scientific, args.per_species, args.since, root, args.offline, rng
            )
        )

    if not records:
        print("\nNothing collected.", file=sys.stderr)
        return 1

    manifest = {
        "source": "iNaturalist API v1 (research-grade observations)",
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observed_since": args.since,
        "since_rationale": (
            "Tier 2 is fine-tuned on iNat21 (collected through 2021); a later "
            "cutoff keeps the evaluation off its training data."
        ),
        "license_filter": LICENSES,
        "per_species_cap": args.per_species,
        "one_photo_per_observer": True,
        "sampling": "uniform random over the research-grade pool",
        "seed": args.seed,
        "max_aspect_ratio": 2.2,
        "count": len(records),
        "photos": records,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    by_species: dict[str, int] = {}
    for r in records:
        by_species[r["scientific_name"]] = by_species.get(r["scientific_name"], 0) + 1
    thin = [s for s, n in by_species.items() if n < max(3, args.per_species // 3)]

    print(f"\n{len(records)} photos across {len(by_species)} species -> {root}")
    print(f"Manifest: {root / 'manifest.json'}")
    if thin:
        print(f"Thin coverage (<{max(3, args.per_species // 3)}): {', '.join(sorted(thin))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
