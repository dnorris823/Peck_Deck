#!/usr/bin/env python3
"""Download the Tier 1 model weights.

The weights are not committed — they are a third-party binary with their own
licence, and the repo stays clean of vendored blobs. This fetches them on
demand and verifies the digest, so a fresh clone can run Tier 1 with:

    python scripts/fetch_models.py

Tier 1 uses Google's AIY ``birds_V1``: MobileNetV2 trained on iNaturalist bird
imagery, 964 species plus a ``background`` class, 224x224 uint8 in and out.
Those shapes are exactly what ``raspberry_pi_code/classification/tier1_tflite.py``
already expects, including the uint8 output dequantisation.

``machine_learning/taxonomy.csv`` is generated from this model's label map by
``scripts/build_taxonomy.py`` and must be regenerated if MODEL_URL changes —
row order is the index contract, so a mismatched pair mislabels every sighting.
"""

import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "machine_learning"

MODEL_URL = (
    "https://www.kaggle.com/api/v1/models/google/aiy/tfLite/"
    "vision-classifier-birds-v1/2/download"
)
MODEL_FILENAME = "aiy_birds_V1_224_uint8.tflite"
# sha256 of the extracted .tflite, so a truncated or swapped download is caught
# here rather than showing up later as nonsense predictions.
MODEL_SHA256 = "8c9d1ed7840eaf9cf98e7b0cac62e527ab254a955c61dd529c006326067a01c1"

EXPECTED_INPUT = (1, 224, 224, 3)
EXPECTED_CLASSES = 965


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download() -> bytes:
    print(f"Downloading {MODEL_URL}")
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "PeckDeck/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        blob = resp.read()
    print(f"  {len(blob):,} bytes")

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name.endswith(".tflite")]
        if len(members) != 1:
            raise SystemExit(f"expected exactly one .tflite in the archive, found {len(members)}")
        extracted = tar.extractfile(members[0])
        if extracted is None:
            raise SystemExit("could not read the .tflite from the archive")
        return extracted.read()


def verify_shapes(path: Path) -> bool:
    """Load the model and confirm it matches what Tier 1 assumes."""
    try:
        import tflite_runtime.interpreter as tflite
    except ImportError:
        try:
            import tensorflow.lite as tflite  # type: ignore[no-redef]
        except ImportError:
            print("  (no tflite runtime here — skipping shape check)")
            return True

    interp = tflite.Interpreter(model_path=str(path))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]

    ok = True
    if tuple(inp["shape"]) != EXPECTED_INPUT:
        print(f"  ! input shape {tuple(inp['shape'])} != {EXPECTED_INPUT}")
        ok = False
    if int(out["shape"][-1]) != EXPECTED_CLASSES:
        print(f"  ! output classes {out['shape'][-1]} != {EXPECTED_CLASSES}")
        ok = False

    scale, _ = out.get("quantization", (0.0, 0))
    print(f"  input  {tuple(inp['shape'])} {inp['dtype'].__name__}")
    print(f"  output {tuple(out['shape'])} {out['dtype'].__name__}  quant_scale={scale}")
    if out["dtype"].__name__ == "uint8" and not scale:
        print("  ! uint8 output with no quantisation scale — confidences would be 0-255")
        ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--print-digest", action="store_true",
                    help="print the downloaded file's sha256 and exit (for pinning)")
    args = ap.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / MODEL_FILENAME

    if target.exists() and not args.force and not args.print_digest:
        print(f"Already present: {target}")
        digest = sha256(target.read_bytes())
        if digest != MODEL_SHA256:
            print(f"  ! sha256 mismatch\n    on disk: {digest}\n    expected: {MODEL_SHA256}")
            print("  Re-run with --force to replace it.")
            return 1
        return 0 if verify_shapes(target) else 1

    data = download()
    digest = sha256(data)

    if args.print_digest:
        print(f"sha256: {digest}")
        return 0

    if digest != MODEL_SHA256:
        print(f"  ! sha256 mismatch\n    got:      {digest}\n    expected: {MODEL_SHA256}",
              file=sys.stderr)
        print("  Refusing to write. If the upstream model was legitimately updated, "
              "confirm the source and update MODEL_SHA256.", file=sys.stderr)
        return 1

    target.write_bytes(data)
    print(f"Wrote {target}")
    return 0 if verify_shapes(target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
