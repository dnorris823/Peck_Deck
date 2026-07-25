#!/usr/bin/env python3
"""Generate ``machine_learning/taxonomy.csv`` from the Tier 1 model's label map.

Tier 1 maps a model output index straight to a taxonomy row
(``tier1_tflite.py`` does ``self._taxa[argmax]``), so the CSV is not a list of
interesting birds — it is the model's own label space, and row order *is* the
contract. Regenerate it whenever the model changes; never hand-edit it.

The AIY label map gives scientific names only. Common names come from
Wikipedia: the article for a bird's binomial almost always redirects to its
English common name ("Cyanocitta cristata" -> "Blue jay"), which the API
reports directly, 50 titles per request.

    python scripts/build_taxonomy.py                 # write the CSV
    python scripts/build_taxonomy.py --dry-run       # report coverage only

Needs network. Output is deterministic, so a re-run should produce no diff.
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LABELMAP_URL = "https://www.gstatic.com/aihub/tfhub/labelmaps/aiy_birds_V1_labelmap.csv"
WIKI_API = "https://en.wikipedia.org/w/api.php"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = REPO_ROOT / "machine_learning" / "taxonomy.csv"
# The curated backyard list. Where it overlaps the model's label space its
# common names win: they are the North American (AOS) names the seed data and
# the demo already use, and Wikipedia prefers the global IOC name — which would
# silently rename "European Starling" to "Common Starling" across the app.
FEEDER_CSV = REPO_ROOT / "machine_learning" / "feeder_species.csv"

# The model's label map is frozen at ~2023 iNaturalist naming. Where a species
# has since been reassigned, record the current name so downstream lookups
# (GBIF enrichment, the seed data, a human reading the CSV) see today's name
# while the row still sits at the index the model actually emits.
CURRENT_NAMES = {
    "Picoides pubescens": "Dryobates pubescens",   # Downy Woodpecker
    "Picoides villosus": "Dryobates villosus",     # Hairy Woodpecker
    "Picoides scalaris": "Dryobates scalaris",     # Ladder-backed Woodpecker
    "Picoides nuttallii": "Dryobates nuttallii",   # Nuttall's Woodpecker
}

# Wikipedia writes article titles in sentence case ("Blue jay"). Ornithological
# convention — and the rest of this project — uses title case ("Blue Jay").
_LOWER_WORDS = {"of", "the", "and", "in", "on", "de", "van", "von", "s"}


def title_case(name: str) -> str:
    """Title-case a common name without mangling apostrophes or hyphens.

    ``str.title()`` turns "Cassin's finch" into "Cassin'S Finch" and
    "Black-capped chickadee" is fine but "grey-crowned" needs both halves.
    """
    def fix_word(word: str, first: bool) -> str:
        if not word:
            return word
        if not first and word.lower() in _LOWER_WORDS:
            return word.lower()
        # Capitalise the first letter only. The part after a hyphen stays
        # lowercase — ornithological convention is "Black-capped Chickadee",
        # not "Black-Capped" — and the part after an apostrophe stays lowercase
        # so "Cassin's" doesn't become "Cassin'S".
        return word[0].upper() + word[1:]

    words = name.split()
    return " ".join(fix_word(w, i == 0) for i, w in enumerate(words))


def fetch_labelmap() -> list[tuple[int, str]]:
    """Return [(index, scientific_name)] sorted by index.

    The file is not in index order — the background class is listed first —
    so sorting is what makes row N correspond to output N.
    """
    with urllib.request.urlopen(LABELMAP_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8")

    rows = []
    for row in csv.DictReader(text.splitlines()):
        rows.append((int(row["id"]), row["name"].strip()))
    rows.sort(key=lambda r: r[0])

    expected = list(range(len(rows)))
    if [r[0] for r in rows] != expected:
        raise SystemExit(
            f"label map indices are not contiguous 0..{len(rows) - 1}; "
            "the index->row contract would be broken"
        )
    return rows


def _wiki_batch(titles: list[str]) -> dict[str, str]:
    """Resolve a batch of up to 50 titles to their redirect targets."""
    params = {
        "action": "query",
        "format": "json",
        "redirects": "1",
        "titles": "|".join(titles),
        "formatversion": "2",
    }
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "PeckDeck-taxonomy-builder/1.0 (bird feeder project)"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)

    query = data.get("query", {})
    resolved = {r["from"]: r["to"] for r in query.get("redirects", [])}
    # A title that is already an article (no redirect) still counts as resolved
    # only if the page exists; a missing page has no common name to offer.
    existing = {
        p["title"] for p in query.get("pages", []) if not p.get("missing")
    }
    for t in titles:
        if t not in resolved and t in existing:
            resolved[t] = t
    return resolved


def resolve_common_names(names: list[str], *, quiet: bool = False) -> dict[str, str]:
    """Map scientific name -> English common name via Wikipedia redirects.

    Paced deliberately: 20 back-to-back batches trip Wikipedia's rate limiter,
    and a 429 that silently drops a batch shows up much later as hundreds of
    species mysteriously lacking a common name.
    """
    out: dict[str, str] = {}
    batch_size = 50
    failed: list[int] = []

    for i in range(0, len(names), batch_size):
        batch = names[i : i + batch_size]
        for attempt in range(5):
            try:
                out.update(_wiki_batch(batch))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Honour Retry-After when offered, else back off hard.
                    wait = float(exc.headers.get("Retry-After") or 0) or 2.0 * (2 ** attempt)
                    time.sleep(min(wait, 30))
                    continue
                if attempt == 4:
                    failed.append(i)
                    print(f"\n  ! batch at {i} failed: {exc}", file=sys.stderr)
                time.sleep(1.5 * (attempt + 1))
            except Exception as exc:
                if attempt == 4:
                    failed.append(i)
                    print(f"\n  ! batch at {i} failed: {exc}", file=sys.stderr)
                time.sleep(1.5 * (attempt + 1))
        else:
            failed.append(i)

        if not quiet:
            done = min(i + batch_size, len(names))
            print(f"  resolved {done}/{len(names)}", end="\r", flush=True)
        time.sleep(0.4)  # be a good citizen; keeps us under the limiter

    if not quiet:
        print()
    if failed:
        raise SystemExit(
            f"{len(failed)} batch(es) never resolved — refusing to write a "
            "taxonomy with silent gaps. Re-run when the network settles."
        )
    return out


def looks_like_a_common_name(title: str, scientific: str, latin: set[str]) -> bool:
    """Reject redirects that landed on something other than an English name.

    A binomial that redirects to its own genus ("Spizella") or to a page with
    parenthetical disambiguation is not a common name, and silently accepting
    it would put a genus label on every sighting of that species.

    ``latin`` holds every binomial in the label map, lowercased. Membership is
    the test — pattern-matching the *shape* of the title does not work, because
    a sentence-case common name ("Blue jay") is indistinguishable from a
    binomial ("Cyanocitta cristata") by regex alone.

    Genus-only targets are accepted: for a monotypic genus the genus *is* the
    English name ("Phainopepla nitens" -> "Phainopepla", "Jabiru mycteria" ->
    "Jabiru"), and where it isn't, Wikipedia pointing at the genus means that
    is the best article available — a genus label beats a raw binomial.
    """
    if not title:
        return False
    clean = strip_disambiguation(title).strip().lower()
    if not clean:
        return False
    if clean == scientific.strip().lower():
        return False  # no English name exists; caller falls back
    if clean in latin:
        return False  # redirected to some *other* species' binomial
    return True


def strip_disambiguation(title: str) -> str:
    """"Sora (bird)" -> "Sora".

    Wikipedia disambiguates common names that collide with something else, and
    the parenthetical is an artefact of the encyclopedia, not part of the name.
    """
    return title.split("(")[0].strip()


def binomial_of(scientific: str) -> str | None:
    """"Junco hyemalis caniceps" -> "Junco hyemalis"; None if not a trinomial."""
    parts = scientific.split()
    return " ".join(parts[:2]) if len(parts) > 2 else None


def load_curated_names() -> dict[tuple[str, str], str]:
    """(genus, species) -> curated common name, from the backyard list."""
    if not FEEDER_CSV.exists():
        return {}
    out = {}
    with open(FEEDER_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["genus"].strip().lower(), row["species"].strip().lower())
            out[key] = row["common_name"].strip()
    return out


def build_rows(labelmap: list[tuple[int, str]], commons: dict[str, str]) -> list[dict]:
    # Every binomial the model knows, so a redirect that lands on a *different*
    # species' name can be recognised as Latin rather than an English name.
    latin = {sci.lower() for _, sci in labelmap if sci.lower() != "background"}
    curated = load_curated_names()

    rows = []
    fallbacks = []
    for idx, sci in labelmap:
        if sci.lower() == "background":
            rows.append({"common_name": "Background", "genus": "", "species": ""})
            continue

        title = commons.get(sci, "")
        if looks_like_a_common_name(title, sci, latin):
            common = title_case(strip_disambiguation(title))
        else:
            # A subspecies rarely has its own article. Its species does, and the
            # species-level common name is the honest label for it.
            parent = binomial_of(sci)
            parent_title = commons.get(parent, "") if parent else ""
            if parent and looks_like_a_common_name(parent_title, parent, latin):
                common = title_case(strip_disambiguation(parent_title))
            else:
                common = sci  # honest fallback: show the binomial
                fallbacks.append((idx, sci))

        current = CURRENT_NAMES.get(sci, sci)
        parts = current.split()
        genus = parts[0] if parts else ""
        species = parts[1] if len(parts) > 1 else ""

        curated_name = curated.get((genus.lower(), species.lower()))
        if curated_name:
            common = curated_name

        rows.append({"common_name": common, "genus": genus, "species": species})

    return rows, fallbacks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report coverage, write nothing")
    ap.add_argument("--out", default=str(OUT_CSV), help="output CSV path")
    args = ap.parse_args()

    print(f"Fetching label map: {LABELMAP_URL}")
    labelmap = fetch_labelmap()
    print(f"  {len(labelmap)} classes (indices 0..{len(labelmap) - 1})")

    sci_names = [n for _, n in labelmap if n.lower() != "background"]
    # Also look up the parent binomial of every subspecies, so a trinomial with
    # no article of its own can inherit its species' common name.
    parents = sorted({b for n in sci_names if (b := binomial_of(n)) and b not in sci_names})
    lookups = sci_names + parents
    print(f"Resolving common names for {len(sci_names)} species "
          f"(+{len(parents)} parent binomials) via Wikipedia...")
    commons = resolve_common_names(lookups)

    rows, fallbacks = build_rows(labelmap, commons)

    named = len(rows) - len(fallbacks) - 1  # minus the background class
    print(f"\nCoverage: {named}/{len(sci_names)} species have a common name "
          f"({100 * named / len(sci_names):.1f}%)")
    if fallbacks:
        print(f"Falling back to the binomial for {len(fallbacks)}:")
        for idx, sci in fallbacks[:15]:
            print(f"  idx={idx:<4} {sci}")
        if len(fallbacks) > 15:
            print(f"  ... and {len(fallbacks) - 15} more")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["common_name", "genus", "species"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
