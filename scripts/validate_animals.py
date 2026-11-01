#!/usr/bin/env python3
"""Score the camera trigger's detector and Tier 2 on feeder animals.

Two questions decide how Peck Deck handles a squirrel:

1. **Does the trigger fire on it?** The detector is EfficientDet-Lite0, trained
   on COCO, which has no squirrel class. This records the best COCO class and
   score for every photo, so we can see whether a squirrel scores as a bird, a
   cat, a dog, or nothing.
2. **Does Tier 2 name it, and at what bar?** ``Prediction.animal`` is the best
   row of ``feeder_animals.csv`` from Tier 2's softmax. The animal set says how
   often the group is right. The bird set says how often a bird would be
   recorded as an animal. ``TIER2_ANIMAL_THRESHOLD`` comes from both.

The rule tested is the Pi's: the animal wins when its confidence meets the bar
and beats the best bird.

Tier 2 runs in process, on the full frame, with the same ``BirdClassifier`` the
inference server loads. The Pi classifies a crop around the detector's box, and
a squirrel the detector misses has no box, so the full frame is the fair input.

    python scripts/build_eval_set.py --set animals --per-species 30
    python scripts/degrade_eval_set.py --root .eval_animals
    python scripts/validate_animals.py
    python scripts/validate_animals.py --variant clean --birds .eval_photos

Ground truth is the directory name: ``<variant>/<Genus_species>/<file>.jpg``.
"""

import argparse
import csv
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from inference_server.classifier import BirdClassifier  # noqa: E402
from inference_server.config import settings as inference_settings  # noqa: E402
from raspberry_pi_code.trigger.bird_detector import BirdDetector  # noqa: E402

DEFAULT_ROOT = REPO_ROOT / ".eval_animals"
DEFAULT_BIRDS = REPO_ROOT / ".eval_photos"
DETECTOR = REPO_ROOT / "machine_learning" / "efficientdet_lite0_detection.tflite"
ANIMALS_CSV = REPO_ROOT / "machine_learning" / "feeder_animals.csv"
# CAMERA_DETECTION_THRESHOLD's default in raspberry_pi_code/config.py.
DETECTION_THRESHOLD = 0.5
# COCO classes a feeder animal could plausibly score as.
TRIGGER_CANDIDATES = {15: "bird", 16: "cat", 17: "dog", 22: "bear"}
SWEEP = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)


def coco_labels(model: Path) -> dict[int, str]:
    """The detector's own label map, packed into the .tflite as a zip member."""
    try:
        with zipfile.ZipFile(model) as z:
            lines = z.read("labelmap.txt").decode().splitlines()
        return dict(enumerate(lines))
    except (KeyError, zipfile.BadZipFile):
        return {}


def groups_by_name() -> dict[str, str]:
    with open(ANIMALS_CSV, newline="", encoding="utf-8") as fh:
        return {r["scientific_name"].strip().lower(): r["group"].strip() for r in csv.DictReader(fh)}


def discover(root: Path, variants: list[str] | None) -> dict[str, list[tuple[Path, str]]]:
    found: dict[str, list[tuple[Path, str]]] = {}
    if not root.is_dir():
        return found
    for variant_dir in sorted(root.iterdir()):
        if not variant_dir.is_dir() or (variants and variant_dir.name not in variants):
            continue
        items = [
            (p, species_dir.name.replace("_", " "))
            for species_dir in sorted(variant_dir.iterdir())
            if species_dir.is_dir()
            for p in sorted(species_dir.glob("*.jpg"))
        ]
        if items:
            found[variant_dir.name] = items
    return dict(sorted(found.items(), key=lambda kv: (kv[0] != "clean", kv[0])))


def measure(path: Path, detector: BirdDetector | None, clf: BirdClassifier) -> dict:
    import numpy as np
    from PIL import Image

    row: dict = {"file": str(path)}
    if detector is not None:
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"))
        scores = detector.scores_by_class(rgb)
        top = max(scores, key=scores.get) if scores else None
        row["det_top_class"] = top
        row["det_top_score"] = scores.get(top, 0.0) if top is not None else 0.0
        row["det_candidates"] = {c: scores.get(c, 0.0) for c in TRIGGER_CANDIDATES}

    pred = clf.classify(path.read_bytes())
    if pred is None:
        row["tier2"] = None
        return row
    row["tier2"] = {
        "bird": pred.scientific_name,
        "bird_conf": pred.confidence,
        "animal": pred.animal.scientific_name if pred.animal else None,
        "group": pred.animal.group if pred.animal else None,
        "animal_conf": pred.animal.confidence if pred.animal else 0.0,
    }
    return row


def animal_wins(t2: dict | None, threshold: float) -> bool:
    return bool(t2) and t2["animal_conf"] >= threshold and t2["animal_conf"] > t2["bird_conf"]


def summarise_detector(rows: list[dict], labels: dict[int, str]) -> dict:
    n = len(rows)
    fires = {
        name: sum(1 for r in rows if r["det_candidates"][cid] >= DETECTION_THRESHOLD)
        for cid, name in TRIGGER_CANDIDATES.items()
    }
    any_fire = sum(
        1 for r in rows if any(s >= DETECTION_THRESHOLD for s in r["det_candidates"].values())
    )
    top = Counter(
        labels.get(r["det_top_class"], str(r["det_top_class"]))
        if r["det_top_score"] >= DETECTION_THRESHOLD else "nothing"
        for r in rows
    )
    return {"n": n, "fires": fires, "any": any_fire, "top": top}


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "   - "


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="animal evaluation tree")
    ap.add_argument("--birds", default=str(DEFAULT_BIRDS),
                    help="bird evaluation tree, for the false-animal rate")
    ap.add_argument("--variant", action="append", help="only this variant (repeatable)")
    ap.add_argument("--detector", default=str(DETECTOR))
    ap.add_argument("--out", help="write every per-photo row as JSON here")
    args = ap.parse_args()

    animals = discover(Path(args.root), args.variant)
    if not animals:
        print(f"No photos under {args.root}. Run build_eval_set.py --set animals", file=sys.stderr)
        return 1
    birds = discover(Path(args.birds), args.variant)

    detector = BirdDetector(args.detector, DETECTION_THRESHOLD)
    if not detector.load():
        print("Detector not loaded. Scoring Tier 2 only", file=sys.stderr)
        detector = None
    labels = coco_labels(Path(args.detector))

    clf = BirdClassifier(
        model_name=inference_settings.MODEL_NAME,
        taxonomy_path=inference_settings.TAXONOMY_PATH,
        image_size=inference_settings.IMAGE_SIZE,
        weights_path=inference_settings.MODEL_PATH,
        device=inference_settings.DEVICE,
        animals_path=str(ANIMALS_CSV),
    )
    if not clf.load():
        print("Tier 2 did not load", file=sys.stderr)
        return 1

    truth_group = groups_by_name()
    report: dict = {"animals": {}, "birds": {}}

    for variant, items in animals.items():
        rows = []
        for path, truth in items:
            row = measure(path, detector, clf)
            row["truth"] = truth
            row["truth_group"] = truth_group.get(truth.lower())
            rows.append(row)
        report["animals"][variant] = rows

    for variant, items in birds.items():
        # The bird set only needs Tier 2. The detector already passes birds.
        report["birds"][variant] = [
            {**measure(path, None, clf), "truth": truth} for path, truth in items
        ]

    # ── Detector on animals ─────────────────────────────────────────────────
    if detector is not None:
        print(f"\nDetector on animals: share of photos with each COCO class >= {DETECTION_THRESHOLD}")
        print(f"  {'variant':12} {'species':26} {'n':>4} " + " ".join(f"{n:>6}" for n in TRIGGER_CANDIDATES.values())
              + f" {'any':>6}  top class")
        for variant, rows in report["animals"].items():
            by_species: dict[str, list[dict]] = {}
            for r in rows:
                by_species.setdefault(r["truth"], []).append(r)
            for species, srows in [*by_species.items(), ("(all)", rows)]:
                if variant != "clean" and species != "(all)":
                    continue
                s = summarise_detector(srows, labels)
                top = ", ".join(f"{k} {v}" for k, v in s["top"].most_common(3))
                print(f"  {variant:12} {species:26} {s['n']:4d} "
                      + " ".join(pct(s["fires"][n], s["n"]) for n in TRIGGER_CANDIDATES.values())
                      + f" {pct(s['any'], s['n'])}  {top}")

    # ── Tier 2 on animals ───────────────────────────────────────────────────
    print("\nTier 2 on animals: right group, and the animal-wins rule at each bar")
    print(f"  {'variant':12} {'species':26} {'n':>4} {'group ok':>8} {'median conf':>11} "
          + " ".join(f"{'@' + format(t, '.1f'):>6}" for t in SWEEP))
    for variant, rows in report["animals"].items():
        by_species: dict[str, list[dict]] = {}
        for r in rows:
            by_species.setdefault(r["truth"], []).append(r)
        for species, srows in [*by_species.items(), ("(all)", rows)]:
            if variant != "clean" and species != "(all)":
                continue
            n = len(srows)
            ok = sum(1 for r in srows if r["tier2"] and r["tier2"]["group"] == r["truth_group"])
            confs = sorted(r["tier2"]["animal_conf"] for r in srows if r["tier2"])
            median = confs[len(confs) // 2] if confs else 0.0
            # Recorded as the right animal group under the Pi's rule.
            hits = [
                sum(1 for r in srows if animal_wins(r["tier2"], t) and r["tier2"]["group"] == r["truth_group"])
                for t in SWEEP
            ]
            print(f"  {variant:12} {species:26} {n:4d} {pct(ok, n):>8} {median:11.2f} "
                  + " ".join(pct(h, n) for h in hits))

    # ── Tier 2 on birds ─────────────────────────────────────────────────────
    if report["birds"]:
        print("\nTier 2 on birds: share a bird would be recorded as an animal at each bar")
        print(f"  {'variant':12} {'n':>5} {'max animal conf':>15} "
              + " ".join(f"{'@' + format(t, '.1f'):>6}" for t in SWEEP))
        pooled: list[dict] = []
        for variant, rows in report["birds"].items():
            pooled.extend(rows)
            n = len(rows)
            top = max((r["tier2"]["animal_conf"] for r in rows if r["tier2"]), default=0.0)
            print(f"  {variant:12} {n:5d} {top:15.3f} "
                  + " ".join(pct(sum(1 for r in rows if animal_wins(r["tier2"], t)), n) for t in SWEEP))
        n = len(pooled)
        top = max((r["tier2"]["animal_conf"] for r in pooled if r["tier2"]), default=0.0)
        print(f"  {'(all)':12} {n:5d} {top:15.3f} "
              + " ".join(pct(sum(1 for r in pooled if animal_wins(r["tier2"], t)), n) for t in SWEEP))

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nRows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
