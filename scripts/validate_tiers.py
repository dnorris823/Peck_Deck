#!/usr/bin/env python3
"""Score Tier 1 and Tier 2 over an evaluation tree, and check their calibration.

``validate_tier1.py`` answers "is Tier 1 wired up correctly?" on 20 clean
Wikipedia photos. This answers the two questions that actually decide product
behaviour:

1. **How accurate is each tier on images like the ones the feeder sees**, and
   which specific degradation breaks it (see ``degrade_eval_set.py``).
2. **Is the confidence signal trustworthy?** The pipeline escalates Tier 1 to
   Tier 2 to Tier 3 when confidence falls below ``CONFIDENCE_THRESHOLD`` (0.5).
   That design is only sound if wrong answers come with *low* confidence. A tier
   that is confidently wrong never escalates, and the app displays the wrong
   bird with nothing anywhere indicating a problem.

Question 2 is unanswerable on a clean set, because a set the model scores 20/20
on contains no wrong answers to examine. It is the real reason this harness
exists, and ``conf-wrong>=thr`` is the column to read: those are the sightings
that would ship a wrong species silently.

Both tiers are driven through the **real Pi clients** — ``TFLiteClassifier`` and
``GPUServerClassifier`` over HTTP — so this measures the deployed path, not a
reimplementation of it.

    # Tier 2 needs the inference server up:  python -m inference_server
    python scripts/validate_tiers.py
    python scripts/validate_tiers.py --tier 1 --variant clean --variant low_light
    python scripts/validate_tiers.py --limit 3 --out report.json

Ground truth is the directory name: ``<variant>/<Genus_species>/<file>.jpg``.
"""

import argparse
import asyncio
import csv
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from raspberry_pi_code.classification.tier1_tflite import TFLiteClassifier  # noqa: E402
from raspberry_pi_code.classification.tier2_gpu import GPUServerClassifier  # noqa: E402

DEFAULT_ROOT = REPO_ROOT / ".eval_photos"
DEFAULT_MODEL = REPO_ROOT / "machine_learning" / "aiy_birds_V1_224_uint8.tflite"
TAXONOMY_CSV = REPO_ROOT / "machine_learning" / "taxonomy.csv"
FEEDER_CSV = REPO_ROOT / "machine_learning" / "feeder_species.csv"
DEFAULT_GPU_URL = "http://localhost:8001"
# Mirrors raspberry_pi_code/config.py — the pipeline accepts at >= threshold.
THRESHOLD = 0.5


def common_names() -> dict[str, str]:
    """scientific name (lowercased) -> curated common name."""
    with open(FEEDER_CSV, newline="", encoding="utf-8") as fh:
        return {
            f"{r['genus'].strip()} {r['species'].strip()}".lower(): r["common_name"].strip()
            for r in csv.DictReader(fh)
        }


def discover(root: Path, variants: list[str] | None, limit: int | None) -> dict[str, list[tuple[Path, str]]]:
    """Map variant name -> [(image path, ground-truth scientific name)]."""
    found: dict[str, list[tuple[Path, str]]] = {}
    for variant_dir in sorted(root.iterdir()):
        if not variant_dir.is_dir():
            continue
        if variants and variant_dir.name not in variants:
            continue
        items: list[tuple[Path, str]] = []
        for species_dir in sorted(variant_dir.iterdir()):
            if not species_dir.is_dir():
                continue
            truth = species_dir.name.replace("_", " ")
            photos = sorted(species_dir.glob("*.jpg"))
            items.extend((p, truth) for p in (photos[:limit] if limit else photos))
        if items:
            found[variant_dir.name] = items
    # "clean" is the baseline every other row is read against, so lead with it.
    return dict(sorted(found.items(), key=lambda kv: (kv[0] != "clean", kv[0])))


async def score(classifier, items: list[tuple[Path, str]], names: dict[str, str]) -> dict:
    """Run one tier over one variant and reduce to a row of statistics."""
    n = correct = genus_ok = failed = 0
    conf_correct: list[float] = []
    conf_wrong: list[float] = []
    confidently_wrong = correct_escalated = 0
    confusion: Counter[str] = Counter()
    # Per-species tallies, because an aggregate hides a species that is failing
    # outright. Worth ruling out one cause first: 56 of the 965 taxonomy entries
    # have no counterpart in Tier 2's label space and are structurally
    # unpredictable -- but all 20 curated feeder species do map, so on this set
    # a zero is a real error rather than a missing label.
    per_species: dict[str, list[int]] = {}

    for path, truth in items:
        result = await classifier.classify(path)
        n += 1
        tally = per_species.setdefault(truth, [0, 0])
        tally[1] += 1
        if result is None:
            failed += 1
            continue

        predicted = (result.scientific_name or "").strip().lower()
        expected = truth.strip().lower()
        exact = predicted == expected
        if not exact:
            # Safety net for naming drift between the curated list and the
            # model's label map: an identical common name is the same bird.
            expected_common = names.get(expected, "")
            exact = bool(expected_common) and (
                result.common_name or ""
            ).strip().lower() == expected_common.lower()

        conf = float(result.confidence)
        if exact:
            correct += 1
            tally[0] += 1
            conf_correct.append(conf)
            if conf < THRESHOLD:
                correct_escalated += 1
        else:
            conf_wrong.append(conf)
            if conf >= THRESHOLD:
                confidently_wrong += 1
            confusion[f"{truth} -> {result.common_name}"] += 1
        if predicted.split()[:1] == expected.split()[:1]:
            genus_ok += 1

    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    return {
        "n": n,
        "failed": failed,
        "top1": correct,
        "top1_pct": round(100 * correct / n, 1) if n else 0.0,
        "genus_pct": round(100 * genus_ok / n, 1) if n else 0.0,
        "mean_conf_correct": mean(conf_correct),
        "mean_conf_wrong": mean(conf_wrong),
        "confidently_wrong": confidently_wrong,
        "confidently_wrong_pct": round(100 * confidently_wrong / n, 1) if n else 0.0,
        "correct_but_escalated": correct_escalated,
        "top_confusions": confusion.most_common(5),
        "per_species": {
            s: {"correct": c, "n": t, "pct": round(100 * c / t, 1) if t else 0.0}
            for s, (c, t) in sorted(per_species.items())
        },
    }


def gpu_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=5) as resp:
            return json.loads(resp.read()).get("model_ready") is True
    except Exception:
        return False


def print_table(tier: str, rows: dict[str, dict]) -> None:
    print(f"\n=== Tier {tier} ===")
    print(f"{'variant':13} {'n':>4} {'top-1':>7} {'genus':>7} "
          f"{'conf-ok':>8} {'conf-bad':>9} {'conf-bad>=' + str(THRESHOLD):>13} {'esc-ok':>7}")
    print("-" * 76)
    for name, r in rows.items():
        fmt = lambda v: f"{v:.3f}" if isinstance(v, float) else "  -  "  # noqa: E731
        print(f"{name:13} {r['n']:4d} {r['top1_pct']:6.1f}% {r['genus_pct']:6.1f}% "
              f"{fmt(r['mean_conf_correct']):>8} {fmt(r['mean_conf_wrong']):>9} "
              f"{r['confidently_wrong']:5d} ({r['confidently_wrong_pct']:4.1f}%) "
              f"{r['correct_but_escalated']:6d}")
    print("\nconf-bad>=thr = wrong answers the pipeline would ACCEPT (no escalation).")
    print("esc-ok        = correct answers it would escalate anyway (wasted tier hop).")

    baseline = rows.get("clean")
    if baseline:
        weak = [(s, d) for s, d in baseline["per_species"].items() if d["pct"] < 50]
        if weak:
            print("\nWeakest species on the clean field set:")
            for s, d in sorted(weak, key=lambda kv: kv[1]["pct"]):
                print(f"  {d['pct']:5.1f}%  {s:28} {d['correct']}/{d['n']}")
        worst = baseline["top_confusions"]
        if worst:
            print("\nMost common clean-set confusions:")
            for pair, count in worst:
                print(f"  {count:3d}x  {pair}")


async def run() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--tier", action="append", choices=["1", "2"],
                    help="tier to evaluate (repeatable; default both)")
    ap.add_argument("--variant", action="append", help="limit to these variants")
    ap.add_argument("--limit", type=int, help="max photos per species (quick runs)")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--taxonomy", default=str(TAXONOMY_CSV))
    ap.add_argument("--gpu-url", default=DEFAULT_GPU_URL)
    ap.add_argument("--out", help="write the full report as JSON")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"No evaluation set at {root} — run scripts/build_eval_set.py",
              file=sys.stderr)
        return 1

    work = discover(root, args.variant, args.limit)
    if not work:
        print(f"No images found under {root}", file=sys.stderr)
        return 1

    tiers = args.tier or ["1", "2"]
    names = common_names()
    total = sum(len(v) for v in work.values())
    print(f"{total} images across {len(work)} variants: {', '.join(work)}")

    report: dict = {"threshold": THRESHOLD, "root": str(root), "tiers": {}}

    for tier in tiers:
        if tier == "1":
            clf = TFLiteClassifier(args.model, args.taxonomy)
            if not clf.load():
                print("Tier 1 failed to load — fetch the model "
                      "(python scripts/fetch_models.py) and install a TFLite runtime.",
                      file=sys.stderr)
                return 1
            label = "1 (local TFLite)"
        else:
            if not gpu_ready(args.gpu_url):
                print(f"Tier 2 not ready at {args.gpu_url} — start it with "
                      "`python -m inference_server` from the repo root.", file=sys.stderr)
                return 1
            clf = GPUServerClassifier(args.gpu_url)
            label = "2 (GPU server)"

        rows: dict[str, dict] = {}
        for variant, items in work.items():
            print(f"  tier {tier}: {variant} ({len(items)})...", flush=True)
            rows[variant] = await score(clf, items, names)
        print_table(label, rows)
        report["tiers"][tier] = {"classifier": label, "variants": rows}

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
