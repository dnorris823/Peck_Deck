#!/usr/bin/env python3
"""Replay the tier chain over measured data to compare threshold settings.

``validate_tiers.py`` scores each tier in isolation. That is not what a user
experiences: they get whatever the *chain* settles on after escalation. This
replays the real logic in ``Pipeline._classify`` over the per-image samples in a
``validate_tiers.py`` report, so a threshold change can be evaluated before it
ships rather than argued about.

It works because the report stores per-image ``(correct, confidence)`` pairs for
both tiers in the same discovery order — index *i* is the same photograph in
each — so the escalation decision can be replayed exactly.

    python scripts/validate_tiers.py --out report.json
    python scripts/simulate_tier_chain.py report.json
    python scripts/simulate_tier_chain.py report.json --pair 0.9 0.6

Tier 3 is not in the report, so escalating past Tier 2 falls to best-effort.
That is also what the deployed pipeline does whenever `CLAUDE_API_KEY` is unset,
which makes it the honest default rather than a simplification. Where Tier 3 *is*
configured, treat the accuracy column as a floor: a real Tier 3 call can only
improve on the best-effort answer it replaces.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from raspberry_pi_code.config import DEFAULT_TIER_THRESHOLDS  # noqa: E402


def replay(t1: dict, t2: dict, thr1: float, thr2: float, only: set[str] | None = None) -> dict:
    """Run every image through the chain at the given thresholds."""
    accepted = accepted_wrong = total = final_correct = 0

    for variant, rows in t1.items():
        if only and variant not in only:
            continue
        s1, s2 = rows["samples"], t2[variant]["samples"]
        if len(s1) != len(s2):
            raise SystemExit(f"tier sample counts differ for '{variant}' — "
                             "the report must come from a single run over one tree")

        for (ok1, c1), (ok2, c2) in zip(s1, s2):
            total += 1
            if c1 >= thr1:
                accepted += 1
                accepted_wrong += not ok1
                final_correct += ok1
            elif c2 >= thr2:
                accepted += 1
                accepted_wrong += not ok2
                final_correct += ok2
            else:
                # Best effort, ranked by closeness to each tier's own bar —
                # matching Pipeline._classify.
                r1 = c1 / thr1 if thr1 else float("inf")
                r2 = c2 / thr2 if thr2 else float("inf")
                final_correct += ok2 if r2 >= r1 else ok1

    return {
        "total": total,
        "accepted_pct": round(100 * accepted / total, 1) if total else 0.0,
        "silent_errors": accepted_wrong,
        "silent_error_pct": round(100 * accepted_wrong / accepted, 1) if accepted else 0.0,
        "final_accuracy_pct": round(100 * final_correct / total, 1) if total else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="JSON written by validate_tiers.py --out")
    ap.add_argument("--pair", nargs=2, type=float, action="append",
                    metavar=("TIER1", "TIER2"),
                    help="extra threshold pair to compare (repeatable)")
    ap.add_argument("--variant", action="append", help="limit to these variants")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    try:
        t1 = report["tiers"]["1"]["variants"]
        t2 = report["tiers"]["2"]["variants"]
    except KeyError:
        raise SystemExit("report must contain both tiers — run validate_tiers.py "
                         "without --tier so it measures 1 and 2 together")
    if "samples" not in next(iter(t1.values())):
        raise SystemExit("report predates per-image samples — re-run validate_tiers.py")

    shipped = (DEFAULT_TIER_THRESHOLDS["local"], DEFAULT_TIER_THRESHOLDS["gpu"])
    pairs = [(0.5, 0.5), shipped] + [tuple(p) for p in (args.pair or [])]

    only = set(args.variant) if args.variant else None
    scope = ", ".join(sorted(only)) if only else f"all {len(t1)} variants"
    print(f"Chain replay over {scope}\n")
    print(f"  {'tier1':>6} {'tier2':>6} {'accepted':>9} {'wrong & accepted':>18} "
          f"{'final top-1':>12}")
    print("  " + "-" * 56)

    for thr1, thr2 in pairs:
        r = replay(t1, t2, thr1, thr2, only)
        note = "  <- shipped" if (thr1, thr2) == shipped else ""
        print(f"  {thr1:6.2f} {thr2:6.2f} {r['accepted_pct']:8.1f}% "
              f"{r['silent_error_pct']:12.1f}% ({r['silent_errors']:4d}) "
              f"{r['final_accuracy_pct']:11.1f}%{note}")

    print("\nwrong & accepted = shown to the user as fact, no escalation, no signal.")
    print("final top-1      = accuracy after the chain settles, best-effort included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
