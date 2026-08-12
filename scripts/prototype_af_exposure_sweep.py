#!/usr/bin/env python3
"""PROTOTYPE — throwaway. Delete once issue #45 records its numbers.

Sweep harness for "Pick the AF and exposure numbers at the glass" (#45).
Produces the concrete thing that ticket asks to react to: real captures at the
window across a small sweep of settings, each with the metadata the camera
actually applied.

Run it ON THE PI, with the rig pointed through the glass at the feeder:

    python scripts/prototype_af_exposure_sweep.py --label dawn
    python scripts/prototype_af_exposure_sweep.py --label overcast-midday
    python scripts/prototype_af_exposure_sweep.py --label dusk

Three passes, swept one axis at a time around a baseline rather than as a
cross-product — a readable contact sheet beats a combinatorial pile.

  A  focus       autofocus_cycle() result, then a manual LensPosition bracket
  B  shutter     FrameDurationLimits ceilings — the motion-freeze / gain trade
  C  exposure    ExposureValue compensation — what shooting through glass needs

Everything it learns comes back as metadata, not as a judgement: each capture
writes a JPEG plus a .json sidecar of what the camera reported, and the actual
ExposureTime / AnalogueGain / LensPosition are printed as it goes. Pass B is the
one that matters most — per #39, flooring the shutter does not underexpose, it
spends AnalogueGain instead, so the sidecars are where the noise cost shows up.

Not production. No error handling beyond what makes it runnable, no tests.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# LensPosition is in DIOPTRES = 1 / distance_in_metres (#39 §1).
# Default bracket spans ~4 m down to ~0.33 m, which should straddle any
# feeder-to-window distance. Narrow it with --distance once you know yours.
DEFAULT_LENS_BRACKET = [0.25, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0]

# Ceilings on frame duration in microseconds. FrameDurationLimits bounds the
# exposure time AE is allowed to choose while leaving AE running (#39 §2).
# None = leave it alone, the baseline. The sensor may not honour the shortest
# of these at full resolution — that is exactly what the sidecars will show.
SHUTTER_CEILINGS_US = [None, 4000, 2000, 1000, 500]

EXPOSURE_VALUES = [-1.0, -0.5, 0.0, 0.5, 1.0]

# Fields worth pulling out of capture_metadata() into the sidecar.
METADATA_KEYS = [
    "ExposureTime",
    "AnalogueGain",
    "DigitalGain",
    "LensPosition",
    "AfState",
    "AfPauseState",
    "Lux",
    "ColourTemperature",
    "FrameDuration",
    "SensorTimestamp",
]


def shutter_label(us):
    if us is None:
        return "auto"
    return f"{us}us_1over{round(1_000_000 / us)}"


class Sweep:
    def __init__(self, outdir, width, height, quality, settle):
        self.outdir = outdir
        self.width = width
        self.height = height
        self.quality = quality
        self.settle = settle
        self.cam = None
        self.has_af = False
        self.shots = 0

    # ---------- lifecycle ----------

    def start(self):
        try:
            from picamera2 import Picamera2
        except ImportError:
            sys.exit(
                "picamera2 not importable. This harness only does anything on the Pi —\n"
                "run it there, with the camera pointed through the glass."
            )

        self.cam = Picamera2()
        cfg = self.cam.create_still_configuration(main={"size": (self.width, self.height)})
        self.cam.configure(cfg)
        self.cam.start()
        # #39 flagged this as unverified: what mode does it actually start in?
        # Answering it is free, and it decides whether _lock_focus() is even needed.
        controls = self.cam.camera_controls
        self.has_af = "AfMode" in controls
        print(f"  camera started at {self.width}x{self.height}")
        print(f"  AfMode present in camera_controls: {self.has_af}")
        if self.has_af:
            print(f"  AfMode control range: {controls.get('AfMode')}")
            print(f"  LensPosition control range: {controls.get('LensPosition')}")
        meta = self.cam.capture_metadata()
        print(f"  metadata at start: {self._pick(meta)}")
        return meta

    def stop(self):
        if self.cam is not None:
            self.cam.stop()
            self.cam.close()
            self.cam = None

    # ---------- capture ----------

    def _pick(self, meta):
        return {k: meta[k] for k in METADATA_KEYS if k in meta}

    def capture(self, name, intent):
        """Capture one frame and write it beside a sidecar of the applied state.

        #39 §3: a control set after start() is only guaranteed to appear in a
        request that was not already queued, and the manual's own advice is to
        synchronise by reading metadata rather than counting frames. So: settle,
        then read metadata, then shoot, then read metadata again — the sidecar
        records both, and a mismatch between `intent` and `applied` is the
        interesting result, not an error.
        """
        time.sleep(self.settle)
        before = self._pick(self.cam.capture_metadata())

        jpg = self.outdir / f"{name}.jpg"
        self.cam.options["quality"] = self.quality
        self.cam.capture_file(str(jpg))

        after = self._pick(self.cam.capture_metadata())
        sidecar = {
            "name": name,
            "intent": intent,
            "applied_before_capture": before,
            "applied_after_capture": after,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "bytes": jpg.stat().st_size,
        }
        (self.outdir / f"{name}.json").write_text(json.dumps(sidecar, indent=2, default=str))

        self.shots += 1
        exp = after.get("ExposureTime")
        gain = after.get("AnalogueGain")
        lens = after.get("LensPosition")
        shutter = f"1/{round(1_000_000 / exp)}s" if exp else "?"
        print(
            f"  [{self.shots:>3}] {name:<34} "
            f"exp={exp}us ({shutter})  gain={gain}  lens={lens}  "
            f"{sidecar['bytes'] // 1024}KB"
        )
        return sidecar

    # ---------- passes ----------

    def pass_a_focus(self, bracket):
        print("\nPASS A — focus")
        if not self.has_af:
            print("  no AfMode control on this module; nothing to sweep. Skipping.")
            return

        from libcamera import controls as libcontrols

        print("  running autofocus_cycle() — does AF converge through glass at all?")
        converged = self.cam.autofocus_cycle()
        chosen = self.cam.capture_metadata().get("LensPosition")
        print(f"  autofocus_cycle() -> converged={converged}  LensPosition={chosen}")
        print(
            "  ^ THE question for this pass. Glass gives AF a second surface to "
            "lock onto;\n    if this lands on the window rather than the feeder, "
            "the manual bracket below is\n    what pi_camera.py will have to use."
        )
        if chosen is not None:
            self.cam.set_controls(
                {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": chosen}
            )
            self.capture(
                f"a_focus_afcycle_{chosen:.2f}d",
                {"pass": "A", "source": "autofocus_cycle", "converged": bool(converged)},
            )

        for d in bracket:
            self.cam.set_controls(
                {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": float(d)}
            )
            metres = (1.0 / d) if d else float("inf")
            self.capture(
                f"a_focus_manual_{d:.2f}d",
                {"pass": "A", "LensPosition": d, "approx_metres": round(metres, 2)},
            )

    def pass_b_shutter(self, lens_position):
        print("\nPASS B — shutter floor (the motion-freeze / gain trade)")
        if lens_position is not None and self.has_af:
            from libcamera import controls as libcontrols

            self.cam.set_controls(
                {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": float(lens_position)}
            )
            print(f"  focus pinned at {lens_position} dioptres for this pass")

        for us in SHUTTER_CEILINGS_US:
            if us is None:
                self.cam.set_controls({"AeEnable": True})
                intent = {"pass": "B", "FrameDurationLimits": None}
            else:
                self.cam.set_controls({"FrameDurationLimits": (100, int(us))})
                intent = {"pass": "B", "FrameDurationLimits": [100, int(us)]}
            self.capture(f"b_shutter_{shutter_label(us)}", intent)

        print(
            "  compare AnalogueGain across these. Per #39, capping the shutter does not\n"
            "  underexpose — AE spends gain instead of time, so the cost of freezing a\n"
            "  bird shows up as noise. The IMX708 tuning table runs gain to 16.0."
        )

    def pass_c_exposure(self, lens_position, shutter_us):
        print("\nPASS C — exposure compensation through glass")
        if shutter_us is not None:
            self.cam.set_controls({"FrameDurationLimits": (100, int(shutter_us))})
            print(f"  shutter ceiling pinned at {shutter_us}us for this pass")
        if lens_position is not None and self.has_af:
            from libcamera import controls as libcontrols

            self.cam.set_controls(
                {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": float(lens_position)}
            )

        for ev in EXPOSURE_VALUES:
            self.cam.set_controls({"ExposureValue": float(ev)})
            self.capture(f"c_ev_{ev:+.1f}".replace(".", "p"), {"pass": "C", "ExposureValue": ev})
        self.cam.set_controls({"ExposureValue": 0.0})


def main():
    p = argparse.ArgumentParser(description="PROTOTYPE AF/exposure sweep at the glass (#45)")
    p.add_argument("--label", required=True, help="light condition, e.g. dawn / overcast-midday / dusk")
    p.add_argument("--outdir", default="sweeps", help="root output directory")
    p.add_argument("--only", choices=["a", "b", "c"], help="run one pass only")
    p.add_argument("--distance", type=float, help="feeder distance in metres; narrows the focus bracket around it")
    p.add_argument("--lens", type=float, help="dioptres to pin for passes B and C (default: whatever AF chose)")
    p.add_argument("--shutter", type=int, help="frame-duration ceiling in us to pin for pass C")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--settle", type=float, default=0.5, help="seconds to wait after set_controls")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.outdir) / f"{stamp}_{args.label}"
    outdir.mkdir(parents=True, exist_ok=True)

    bracket = DEFAULT_LENS_BRACKET
    if args.distance:
        centre = 1.0 / args.distance
        bracket = [round(centre * m, 3) for m in (0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4)]

    print(f"PROTOTYPE sweep — {args.label}")
    print(f"  writing to {outdir.resolve()}")

    sweep = Sweep(outdir, args.width, args.height, args.quality, args.settle)
    start_meta = sweep.start()
    lens = args.lens

    try:
        if args.only in (None, "a"):
            sweep.pass_a_focus(bracket)
            if lens is None:
                lens = sweep.cam.capture_metadata().get("LensPosition")
        if args.only in (None, "b"):
            sweep.pass_b_shutter(lens)
        if args.only in (None, "c"):
            sweep.pass_c_exposure(lens, args.shutter)
    finally:
        (outdir / "_session.json").write_text(
            json.dumps(
                {
                    "label": args.label,
                    "args": vars(args),
                    "lens_bracket": bracket,
                    "shutter_ceilings_us": SHUTTER_CEILINGS_US,
                    "exposure_values": EXPOSURE_VALUES,
                    "metadata_at_start": start_meta,
                    "shots": sweep.shots,
                },
                indent=2,
                default=str,
            )
        )
        sweep.stop()

    print(f"\n{sweep.shots} captures in {outdir.resolve()}")
    print("Pull the whole directory back and we'll pick the numbers off it together.")


if __name__ == "__main__":
    main()
