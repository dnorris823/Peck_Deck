#!/usr/bin/env python3
"""Download the model weights the Pi runs.

The weights are not committed — they are third-party binaries with their own
licences, and the repo stays clean of vendored blobs. This fetches them on
demand and verifies each digest, so a fresh clone can run with:

    python scripts/fetch_models.py

Two models:

* Tier 1 uses Google's AIY ``birds_V1``: MobileNetV2 trained on iNaturalist bird
  imagery, 964 species plus a ``background`` class, 224x224 uint8 in and out.
  Those shapes are exactly what ``raspberry_pi_code/classification/tier1_tflite.py``
  already expects, including the uint8 output dequantisation.

  ``machine_learning/taxonomy.csv`` is generated from this model's label map by
  ``scripts/build_taxonomy.py`` and must be regenerated if its URL changes —
  row order is the index contract, so a mismatched pair mislabels every sighting.

* The camera trigger uses EfficientDet-Lite0, a COCO object detector from the
  TensorFlow team, to decide bird or no bird. 320x320 uint8 in, and the standard
  four post-processed outputs: boxes, classes, scores, count. COCO "bird" is
  class 15 in its label map, which ``raspberry_pi_code/trigger/bird_detector.py``
  hard-codes as ``BIRD_CLASS_ID``.
"""

import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "machine_learning"

sys.path.insert(0, str(REPO_ROOT))
from raspberry_pi_code.tflite_loader import import_tflite  # noqa: E402


@dataclass(frozen=True)
class ModelSpec:
    name: str
    url: str
    filename: str
    # sha256 of the extracted .tflite, so a truncated or swapped download is
    # caught here rather than showing up later as nonsense predictions.
    sha256: str
    input_shape: tuple[int, ...]
    output_count: int
    # Last dimension of the first output: classes for Tier 1, 4 box coords for
    # the detector.
    first_output_last_dim: int


MODELS = (
    ModelSpec(
        name="tier1",
        url=(
            "https://www.kaggle.com/api/v1/models/google/aiy/tfLite/"
            "vision-classifier-birds-v1/2/download"
        ),
        filename="aiy_birds_V1_224_uint8.tflite",
        sha256="8c9d1ed7840eaf9cf98e7b0cac62e527ab254a955c61dd529c006326067a01c1",
        input_shape=(1, 224, 224, 3),
        output_count=1,
        first_output_last_dim=965,
    ),
    ModelSpec(
        name="detector",
        url=(
            "https://www.kaggle.com/api/v1/models/tensorflow/efficientdet/tfLite/"
            "lite0-detection-metadata/1/download"
        ),
        filename="efficientdet_lite0_detection.tflite",
        sha256="2e04c53bfeac0ac2a30c057c7e2a777594ce39baaac35a92f74fb1e8c4fc4e0b",
        input_shape=(1, 320, 320, 3),
        output_count=4,
        first_output_last_dim=4,
    ),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(spec: ModelSpec) -> bytes:
    print(f"Downloading {spec.name}: {spec.url}")
    req = urllib.request.Request(spec.url, headers={"User-Agent": "PeckDeck/1.0"})
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


def _shape(detail: dict) -> tuple[int, ...]:
    return tuple(int(d) for d in detail["shape"])


def verify_shapes(spec: ModelSpec, path: Path) -> bool:
    """Load the model and confirm it matches what the Pi code assumes."""
    tflite = import_tflite()
    if tflite is None:
        print("  (no tflite runtime here — skipping shape check)")
        return True

    interp = tflite.Interpreter(model_path=str(path))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    outs = interp.get_output_details()
    out = outs[0]

    ok = True
    if _shape(inp) != spec.input_shape:
        print(f"  ! input shape {_shape(inp)} != {spec.input_shape}")
        ok = False
    if inp["dtype"].__name__ != "uint8":
        print(f"  ! input dtype {inp['dtype'].__name__} != uint8")
        ok = False
    if len(outs) != spec.output_count:
        print(f"  ! {len(outs)} outputs != {spec.output_count}")
        ok = False
    if int(out["shape"][-1]) != spec.first_output_last_dim:
        print(f"  ! first output last dim {out['shape'][-1]} != {spec.first_output_last_dim}")
        ok = False

    scale, _ = out.get("quantization", (0.0, 0))
    print(f"  input  {_shape(inp)} {inp['dtype'].__name__}")
    for o in outs:
        print(f"  output {_shape(o)} {o['dtype'].__name__}")
    if out["dtype"].__name__ == "uint8" and not scale:
        print("  ! uint8 output with no quantisation scale — confidences would be 0-255")
        ok = False
    return ok


def fetch(spec: ModelSpec, force: bool, print_digest: bool) -> bool:
    target = MODEL_DIR / spec.filename

    if target.exists() and not force and not print_digest:
        print(f"Already present: {target}")
        digest = sha256(target.read_bytes())
        if digest != spec.sha256:
            print(f"  ! sha256 mismatch\n    on disk: {digest}\n    expected: {spec.sha256}")
            print("  Re-run with --force to replace it.")
            return False
        return verify_shapes(spec, target)

    data = download(spec)
    digest = sha256(data)

    if print_digest:
        print(f"  sha256: {digest}")
        return True

    if digest != spec.sha256:
        print(f"  ! sha256 mismatch\n    got:      {digest}\n    expected: {spec.sha256}",
              file=sys.stderr)
        print("  Refusing to write. If the upstream model was legitimately updated, "
              "confirm the source and update its sha256.", file=sys.stderr)
        return False

    target.write_bytes(data)
    print(f"Wrote {target}")
    return verify_shapes(spec, target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--print-digest", action="store_true",
                    help="print each downloaded file's sha256 and exit (for pinning)")
    ap.add_argument("--only", choices=[m.name for m in MODELS],
                    help="fetch one model instead of all of them")
    args = ap.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    specs = [m for m in MODELS if args.only in (None, m.name)]
    results = [fetch(spec, args.force, args.print_digest) for spec in specs]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
