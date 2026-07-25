#!/usr/bin/env python3
"""Suite C3 — trigger-peripheral loopback test (see HARDWARE_TEST_PLAN.md).

Proves the real trigger classes enqueue exactly one event per edge, using a
jumper between two header pins instead of a PIR / IR-beam sensor:

    BCM27 (physical pin 13, driven output) ──jumper──► BCM17 (physical pin 11, input)

The driver pin is toggled with `pinctrl`, deliberately *outside* the process
under test, so the edge arrives through the same silicon path a real sensor
would use. Run on the Pi, from the repo root:

    .venv/bin/python3 scripts/gpio_loopback_test.py

Exits non-zero if any case fails, so it can gate a bring-up run.
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raspberry_pi_code.trigger.base import TriggerBase  # noqa: E402
from raspberry_pi_code.trigger.ir_beam_trigger import IRBeamTrigger  # noqa: E402
from raspberry_pi_code.trigger.pir_trigger import PIRTrigger  # noqa: E402

# `bouncetime=200` in both trigger classes. Edges spaced under this are one
# event by design; spaced over it they are distinct. Both are asserted below.
BOUNCE_MS = 200
SETTLE = 0.05
QUIET = 0.6  # how long to wait for stragglers before calling a burst finished

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def drive(pin: int, level: int) -> None:
    subprocess.run(
        ["pinctrl", "set", str(pin), "op", "dh" if level else "dl"],
        check=True,
    )


def release(pin: int) -> None:
    subprocess.run(["pinctrl", "set", str(pin), "ip"], check=True)


async def drain(trigger: TriggerBase, quiet: float = QUIET) -> list[float]:
    """Collect events until the line has been quiet for `quiet` seconds."""
    events: list[float] = []
    while True:
        try:
            events.append(await asyncio.wait_for(trigger.next_event(), quiet))
        except asyncio.TimeoutError:
            return events


async def run_case(
    label: str,
    trigger: TriggerBase,
    out_pin: int,
    edges: list[tuple[int, float]],
    expected: int,
) -> None:
    """Drive `edges` as (level, delay_after) then assert the event count."""
    for level, delay in edges:
        drive(out_pin, level)
        await asyncio.sleep(delay)
    got = len(await drain(trigger))
    record(label, got == expected, f"expected {expected} event(s), got {got}")


async def test_pir(in_pin: int, out_pin: int) -> None:
    print("\nPIRTrigger — RISING edge, internal pull-down")
    drive(out_pin, 0)
    await asyncio.sleep(0.2)

    async with PIRTrigger(in_pin) as trig:
        await asyncio.sleep(0.2)
        stray = await drain(trig, 0.4)
        record("C3.1 quiet after setup", not stray, f"{len(stray)} spurious event(s)")

        await run_case(
            "C3.2 single RISING", trig, out_pin,
            [(1, SETTLE)], expected=1,
        )
        await run_case(
            "C3.3 FALLING ignored", trig, out_pin,
            [(0, SETTLE)], expected=0,
        )
        # Two rising edges inside the debounce window collapse to one.
        await run_case(
            "C3.4 debounce collapses fast edges", trig, out_pin,
            [(1, 0.02), (0, 0.02), (1, SETTLE)], expected=1,
        )
        # Spaced beyond the debounce window they stay distinct.
        await asyncio.sleep(0.3)
        await run_case(
            "C3.5 three spaced RISING edges", trig, out_pin,
            [(0, 0.3), (1, 0.3), (0, 0.3), (1, 0.3), (0, 0.3), (1, SETTLE)],
            expected=3,
        )


async def test_ir_beam(in_pin: int, out_pin: int) -> None:
    print("\nIRBeamTrigger — FALLING edge, internal pull-up")
    drive(out_pin, 1)
    await asyncio.sleep(0.2)

    async with IRBeamTrigger(in_pin) as trig:
        await asyncio.sleep(0.2)
        stray = await drain(trig, 0.4)
        record("C3.6 quiet after setup", not stray, f"{len(stray)} spurious event(s)")

        await run_case(
            "C3.7 single FALLING (beam broken)", trig, out_pin,
            [(0, SETTLE)], expected=1,
        )
        await run_case(
            "C3.8 RISING ignored (beam restored)", trig, out_pin,
            [(1, SETTLE)], expected=0,
        )
        await asyncio.sleep(0.3)
        await run_case(
            "C3.9 two spaced FALLING edges", trig, out_pin,
            [(0, 0.3), (1, 0.3), (0, SETTLE)], expected=2,
        )


async def main() -> int:
    ap = argparse.ArgumentParser(description="C3 GPIO loopback trigger test")
    ap.add_argument("--in-pin", type=int, default=17, help="BCM input pin (default 17)")
    ap.add_argument("--out-pin", type=int, default=27, help="BCM driver pin (default 27)")
    args = ap.parse_args()

    print(f"C3 loopback: BCM{args.out_pin} (out) --jumper--> BCM{args.in_pin} (in)")
    print(f"debounce window: {BOUNCE_MS} ms")

    try:
        await test_pir(args.in_pin, args.out_pin)
        await test_ir_beam(args.in_pin, args.out_pin)
    finally:
        release(args.out_pin)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} cases passed")
    if passed != total:
        print("FAILED: " + ", ".join(n for n, ok, _ in results if not ok))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
