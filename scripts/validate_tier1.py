#!/usr/bin/env python3
"""Measure Tier 1 accuracy on known bird photos.

Phase 4 could report latency but never accuracy — the model was a stand-in, so
every label was meaningless by construction. This drives the *real*
``TFLiteClassifier`` over photos whose species is known, which tests two things
at once:

* the model predicts the right bird, and
* ``taxonomy.csv`` is index-aligned with the model's output. A taxonomy off by
  even one row mislabels everything while still looking plausible, and no
  latency or shape check would catch it.

Ground truth is ``machine_learning/feeder_species.csv``; photos are each
species' Wikipedia lead image, cached under ``--cache-dir``.

    python scripts/validate_tier1.py                    # fetch + evaluate
    python scripts/validate_tier1.py --offline          # use cached photos only

Caveat: encyclopedia lead images are clean, centred, well-lit birds. Treat the
score as an upper bound, not what a feeder camera will see.
"""

import argparse
import asyncio
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from raspberry_pi_code.classification.tier1_tflite import TFLiteClassifier  # noqa: E402

FEEDER_CSV = REPO_ROOT / "machine_learning" / "feeder_species.csv"
TAXONOMY_CSV = REPO_ROOT / "machine_learning" / "taxonomy.csv"
DEFAULT_MODEL = REPO_ROOT / "machine_learning" / "aiy_birds_V1_224_uint8.tflite"
WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "PeckDeck-tier1-validation/1.0 (bird feeder project)"}


def _get(url: str, timeout: int = 90) -> bytes:
    """GET with backoff. Wikimedia rate-limits bursts of image fetches."""
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or 2.0 * (2 ** attempt)
            time.sleep(min(wait, 30))
    raise RuntimeError("unreachable")


def wiki_image_url(title: str, width: int = 800) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": str(width),
        "redirects": "1",
        "titles": title,
    }
    data = json.loads(_get(f"{WIKI_API}?{urllib.parse.urlencode(params)}", timeout=60))
    for page in data.get("query", {}).get("pages", []):
        thumb = page.get("thumbnail", {}).get("source")
        if thumb:
            return thumb
    return None


def fetch_photo(common: str, scientific: str, cache: Path, offline: bool) -> Path | None:
    slug = scientific.replace(" ", "_")
    for ext in (".jpg", ".png"):
        p = cache / f"{slug}{ext}"
        if p.exists():
            return p
    if offline:
        return None

    # Prefer the common-name article; the binomial redirects there anyway, but
    # asking directly avoids a species page that lacks a lead image.
    url = wiki_image_url(common) or wiki_image_url(scientific)
    if not url:
        return None

    ext = ".png" if url.lower().endswith(".png") else ".jpg"
    target = cache / f"{slug}{ext}"
    target.write_bytes(_get(url))
    time.sleep(1.0)  # Wikimedia rate-limits image bursts harder than the API
    return target


def load_ground_truth() -> list[tuple[str, str]]:
    with open(FEEDER_CSV, newline="", encoding="utf-8") as fh:
        return [
            (r["common_name"].strip(), f"{r['genus'].strip()} {r['species'].strip()}")
            for r in csv.DictReader(fh)
        ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--taxonomy", default=str(TAXONOMY_CSV))
    ap.add_argument("--cache-dir", default=str(REPO_ROOT / ".validation_photos"))
    ap.add_argument("--offline", action="store_true", help="use cached photos only")
    args = ap.parse_args()

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    clf = TFLiteClassifier(args.model, args.taxonomy)
    if not clf.load():
        print("Tier 1 failed to load — is the model fetched? "
              "(python scripts/fetch_models.py)", file=sys.stderr)
        return 1

    truth = load_ground_truth()
    print(f"Evaluating {len(truth)} species against {Path(args.model).name}\n")

    hits = genus_hits = evaluated = 0
    misses: list[str] = []

    for common, scientific in truth:
        photo = fetch_photo(common, scientific, cache, args.offline)
        if photo is None:
            print(f"  {'SKIP':6} {common:28} (no photo)")
            continue

        result = asyncio.run(clf.classify(photo))
        evaluated += 1
        if result is None:
            print(f"  {'FAIL':6} {common:28} classifier returned nothing")
            misses.append(common)
            continue

        exact = result.common_name.strip().lower() == common.strip().lower()
        same_genus = (
            result.scientific_name.split()[:1] == scientific.split()[:1]
            if result.scientific_name else False
        )
        hits += exact
        genus_hits += same_genus

        if exact:
            mark = "OK"
        elif same_genus:
            mark = "GENUS"
        else:
            mark = "MISS"
            misses.append(f"{common} -> {result.common_name}")
        print(f"  {mark:6} {common:28} predicted {result.common_name:26} "
              f"{result.confidence:.3f}")

    if not evaluated:
        print("\nNo photos evaluated.", file=sys.stderr)
        return 1

    print(f"\nTop-1 species: {hits}/{evaluated} ({100 * hits / evaluated:.0f}%)")
    print(f"Correct genus: {genus_hits}/{evaluated} ({100 * genus_hits / evaluated:.0f}%)")
    if misses:
        print("Misses:")
        for m in misses:
            print(f"  {m}")

    # A correct model with a misaligned taxonomy scores near zero, so this
    # doubles as the index-alignment check.
    if hits == 0:
        print("\nZero correct: the taxonomy is probably not aligned with the "
              "model's output indices.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
