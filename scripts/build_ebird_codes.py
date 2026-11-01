#!/usr/bin/env python3
"""Generate ``backend/species/ebird_codes.csv`` from the taxonomy and eBird.

The species page links to eBird and All About Birds, and both key their pages
on eBird's six-letter species code ("blujay"), not on a name. This maps every
row of ``machine_learning/taxonomy.csv`` to its code, keyed by the taxonomy's
own names, because those are the names the Pi uploads and the species table
stores.

The file lives under ``backend/`` because the API container is built from that
directory alone and cannot read ``machine_learning/``.

The taxonomy's scientific names are frozen at the model's ~2023 naming, and
eBird has moved many genera since ("Accipiter cooperii" is now "Astur
cooperii"). A row that misses on scientific name falls back to its common name,
then to ``ALIASES`` for the few that eBird renamed or lumped.

    python scripts/build_ebird_codes.py

Needs network, no API key. Refuses to write if any taxonomy row stays
unresolved. Regenerate after rebuilding the taxonomy; never hand-edit.
"""

import csv
import io
import sys
import urllib.request
from pathlib import Path

EBIRD_TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird?fmt=csv&cat=species"
REPO_ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_CSV = REPO_ROOT / "machine_learning" / "taxonomy.csv"
OUT_CSV = REPO_ROOT / "backend" / "species" / "ebird_codes.csv"

# Taxonomy names that match eBird on neither scientific nor common name.
ALIASES = {
    "emberiza schoeniclus": "reebun",      # Reed Bunting, now Schoeniclus
    "carduelis cannabina": "eurlin1",      # Eurasian Linnet, now Linaria
    "sylvia communis": "grewhi1",          # Greater Whitethroat, now Curruca
    "larus thayeri": "y00478",             # Thayer's Gull, lumped into Iceland Gull
    "threskiornis moluccus": "ausibi1",    # Australian Ibis
    "porphyrio martinicus": "purgal2",     # Purple Gallinule
    "chroicocephalus scopulinus": "silgul2",  # Red-billed Gull, lumped into Silver Gull
    "corvus monedula": "eurjac",           # Eurasian Jackdaw, now Coloeus
}


def norm_common(name: str) -> str:
    """Fold the spelling differences between the taxonomy and eBird."""
    return name.lower().replace("grey", "gray").replace("-", " ").replace("'", "").strip()


def fetch_ebird() -> tuple[dict[str, str], dict[str, str]]:
    req = urllib.request.Request(
        EBIRD_TAXONOMY_URL, headers={"User-Agent": "PeckDeck-ebird-codes/1.0 (bird feeder project)"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    by_sci, by_common = {}, {}
    for row in csv.DictReader(io.StringIO(text)):
        by_sci[row["SCIENTIFIC_NAME"].lower()] = row["SPECIES_CODE"]
        by_common[norm_common(row["COMMON_NAME"])] = row["SPECIES_CODE"]
    return by_sci, by_common


def main() -> int:
    print(f"Fetching eBird taxonomy: {EBIRD_TAXONOMY_URL}")
    by_sci, by_common = fetch_ebird()
    print(f"  {len(by_sci)} species")

    rows, missing = [], []
    with open(TAXONOMY_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row["genus"]:
                continue  # the model's Background class
            sci = f"{row['genus']} {row['species']}"
            code = (
                by_sci.get(sci.lower())
                or by_common.get(norm_common(row["common_name"]))
                or ALIASES.get(sci.lower())
            )
            if code:
                rows.append({"common_name": row["common_name"], "scientific_name": sci, "ebird_code": code})
            else:
                missing.append(f"{row['common_name']} ({sci})")

    if missing:
        print(f"\n{len(missing)} taxonomy rows have no eBird code. Add them to ALIASES:")
        for m in missing:
            print(f"  {m}")
        return 1

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["common_name", "scientific_name", "ebird_code"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
