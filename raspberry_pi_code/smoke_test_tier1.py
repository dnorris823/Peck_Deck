"""End-to-end Tier-1 hardware smoke test (Hardware Test Plan, Suite B + E).

Captures a real image with the Pi camera, runs the project's own
TFLiteClassifier against it, and reports load/inference latency plus SoC
temperature before and after. Uses the stand-in model unless MODEL_PATH /
TAXONOMY_PATH point elsewhere (e.g. the real INatVision model).

Run from repo root:
    MODEL_PATH=machine_learning/stand_in_smoketest_224_uint8.tflite \
    TAXONOMY_PATH=machine_learning/taxonomy.csv \
    .venv/bin/python -m raspberry_pi_code.smoke_test_tier1
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path

from raspberry_pi_code.camera.pi_camera import PiCamera
from raspberry_pi_code.classification.tier1_tflite import TFLiteClassifier

ROOT = Path(__file__).parents[1]
MODEL = os.getenv("MODEL_PATH", str(ROOT / "machine_learning" / "stand_in_smoketest_224_uint8.tflite"))
TAXO = os.getenv("TAXONOMY_PATH", str(ROOT / "machine_learning" / "taxonomy.csv"))


def temp_c() -> str:
    try:
        return subprocess.check_output(["vcgencmd", "measure_temp"], text=True).strip()
    except Exception:
        return "temp=unavailable"


async def main() -> int:
    out = ROOT / "smoke_capture.jpg"
    print(f"[thermal] before capture: {temp_c()}")

    # --- Suite B3: capture via project camera code ---
    t0 = time.monotonic()
    async with PiCamera(1920, 1080, 90) as cam:
        await cam.capture(out)
    cap_ms = (time.monotonic() - t0) * 1000
    size = out.stat().st_size if out.exists() else 0
    real = size > 20_000  # dummy fallback JPEGs are tiny
    print(f"[camera] captured {out.name}: {size} bytes in {cap_ms:.0f} ms "
          f"({'REAL sensor image' if real else 'DUMMY fallback — camera not active!'})")

    # --- Suite E2: model load ---
    clf = TFLiteClassifier(MODEL, TAXO)
    t0 = time.monotonic()
    ok = clf.load()
    load_ms = (time.monotonic() - t0) * 1000
    print(f"[tflite] model={Path(MODEL).name} load ok={ok} in {load_ms:.0f} ms")
    if not ok:
        return 1

    # --- Suite E3/E4: inference + latency (10 runs) ---
    latencies = []
    result = None
    for _ in range(10):
        t0 = time.monotonic()
        result = await clf.classify(out)
        latencies.append((time.monotonic() - t0) * 1000)
    avg = sum(latencies) / len(latencies)
    print(f"[tflite] inference x{len(latencies)}: "
          f"min={min(latencies):.1f} avg={avg:.1f} max={max(latencies):.1f} ms")
    if result:
        print(f"[result] {result.common_name} ({result.scientific_name}) "
              f"conf={result.confidence:.3f} tier={result.tier_used}")
    print(f"[thermal] after inference: {temp_c()}")
    print("[note] labels are meaningless with the stand-in model; this validates "
          "the capture→preprocess→invoke→argmax→taxonomy path, not accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
