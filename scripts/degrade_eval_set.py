#!/usr/bin/env python3
"""Derive feeder-camera degradations from a clean evaluation set.

The field photos from ``build_eval_set.py`` are already harder than Wikipedia
lead images, but they answer only "how good is the model on real photos?" They
cannot answer *why* it fails, because every hard photo is hard in several ways
at once — small, blurred, backlit and compressed together.

So each degradation is applied to the same clean images **one at a time**. The
resulting per-variant scores are an ablation: they say which specific property
of a feeder frame the models are brittle to, which is the actionable form of the
answer. Camera placement fixes a framing problem; a shutter-speed change fixes a
motion-blur problem; neither fixes the other.

    python scripts/degrade_eval_set.py                    # every variant
    python scripts/degrade_eval_set.py --variant motion_blur --variant distant

Output mirrors the clean tree: ``<root>/<variant>/<Genus_species>/<file>.jpg``.
Deterministic — a given file and variant always produce the same pixels.

Caveat worth stating: without a subject detector these transforms are applied
blind to where the bird actually is. ``off_center`` crops toward a corner and
``occluded`` lays a bar across the frame without knowing what they cover, so a
small number of images will have the bird clipped harder than intended. That
biases the two spatial variants pessimistically; it does not affect the others.
"""

import argparse
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / ".eval_photos"
JPEG_QUALITY = 92  # variants that aren't *about* compression shouldn't add much


def _rng(variant: str, path: Path) -> random.Random:
    return random.Random(f"{variant}:{path.name}")


def distant(img: Image.Image, rng: random.Random) -> Image.Image:
    """Bird further from the lens: subject shrinks, frame size stays.

    The vacated frame is filled with a blurred, over-scaled copy of the same
    photo rather than flat grey — a real distant shot has *more* background, not
    a matte border, and a flat border would hand the model a trivial cue that
    something has been done to the image.
    """
    w, h = img.size
    scale = rng.uniform(0.35, 0.5)
    small = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    bg = img.resize((int(w * 1.6), int(h * 1.6)), Image.LANCZOS)
    bg = bg.crop((0, 0, w, h)).filter(ImageFilter.GaussianBlur(radius=max(w, h) / 90))
    bg = ImageEnhance.Brightness(bg).enhance(1.05)

    x = (w - small.width) // 2 + rng.randint(-w // 12, w // 12)
    y = (h - small.height) // 2 + rng.randint(-h // 12, h // 12)
    bg.paste(small, (max(0, x), max(0, y)))
    return bg


def off_center(img: Image.Image, rng: random.Random) -> Image.Image:
    """Subject pushed to an edge, as when a bird lands off the framed perch."""
    w, h = img.size
    keep = 0.75
    cw, ch = int(w * keep), int(h * keep)
    # Bounded offset: a full-slack crop would too often exclude the bird entirely.
    max_dx, max_dy = int((w - cw) * 0.6), int((h - ch) * 0.6)
    dx = rng.choice([-1, 1]) * rng.randint(max_dx // 2, max_dx)
    dy = rng.choice([-1, 1]) * rng.randint(max_dy // 2, max_dy)
    left = min(max(0, (w - cw) // 2 + dx), w - cw)
    top = min(max(0, (h - ch) // 2 + dy), h - ch)
    return img.crop((left, top, left + cw, top + ch)).resize((w, h), Image.LANCZOS)


def motion_blur(img: Image.Image, rng: random.Random) -> Image.Image:
    """Wingbeat / hop smear. PIL kernels cap at 5x5, so blur by repetition."""
    horizontal = [
        0, 0, 0, 0, 0,
        0, 0, 0, 0, 0,
        1, 1, 1, 1, 1,
        0, 0, 0, 0, 0,
        0, 0, 0, 0, 0,
    ]
    diagonal = [
        1, 0, 0, 0, 0,
        0, 1, 0, 0, 0,
        0, 0, 1, 0, 0,
        0, 0, 0, 1, 0,
        0, 0, 0, 0, 1,
    ]
    kernel = rng.choice([horizontal, diagonal])
    out = img
    for _ in range(rng.randint(2, 3)):
        out = out.filter(ImageFilter.Kernel((5, 5), kernel, scale=sum(kernel)))
    return out


def low_light(img: Image.Image, rng: random.Random) -> Image.Image:
    """Dawn/dusk: the feeder's busiest hours are also its darkest.

    Gamma down for exposure, contrast down for flat light, then sensor noise —
    because a real camera does not simply darken, it darkens *and gets noisy*,
    and denoising artefacts are part of what the classifier has to survive.
    """
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = np.power(arr, rng.uniform(1.9, 2.4))
    arr = arr * rng.uniform(0.75, 0.9)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, 0.035, arr.shape)
    arr = np.clip(arr + noise, 0.0, 1.0)
    out = Image.fromarray((arr * 255).astype(np.uint8))
    return ImageEnhance.Contrast(out).enhance(0.85)


def backlit(img: Image.Image, rng: random.Random) -> Image.Image:
    """Bird against a bright sky — the single most common feeder-cam exposure."""
    w, h = img.size
    arr = np.asarray(img, dtype=np.float32) / 255.0

    # Horizontal brightness ramp standing in for a blown-out sky on one side.
    ramp = np.linspace(0.0, 1.0, w, dtype=np.float32)
    if rng.random() < 0.5:
        ramp = ramp[::-1]
    glare = (ramp**2)[None, :, None] * rng.uniform(0.45, 0.7)
    arr = np.clip(arr + glare, 0.0, 1.0)

    # Subject sits in shadow: lift the blacks and crush local contrast.
    arr = arr * 0.72 + 0.1
    out = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    return ImageEnhance.Contrast(out).enhance(0.7)


def sensor_soft(img: Image.Image, rng: random.Random) -> Image.Image:
    """Detail loss of a small subject on a 1080p sensor: downscale, upscale back."""
    w, h = img.size
    f = rng.uniform(0.18, 0.28)
    small = img.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
    return small.resize((w, h), Image.BICUBIC)


def occluded(img: Image.Image, rng: random.Random) -> Image.Image:
    """Feeder hardware in the way — a pole, a perch, a cage bar."""
    out = img.copy()
    w, h = out.size
    draw = ImageDraw.Draw(out)
    shade = rng.randint(30, 90)
    colour = (shade, shade - 5, shade - 12)

    bar_w = int(w * rng.uniform(0.09, 0.15))
    x = int(w * rng.uniform(0.3, 0.6))
    draw.rectangle([x, 0, x + bar_w, h], fill=colour)

    if rng.random() < 0.5:  # a perch crossing the lower frame
        bar_h = int(h * rng.uniform(0.06, 0.1))
        y = int(h * rng.uniform(0.55, 0.8))
        draw.rectangle([0, y, w, y + bar_h], fill=colour)
    return out


def jpeg_lossy(img: Image.Image, rng: random.Random) -> Image.Image:
    """Aggressive recompression, as on a bandwidth-constrained upload."""
    import io

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(18, 28))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def field_combo(img: Image.Image, rng: random.Random) -> Image.Image:
    """Everything at once, mildly — the realistic bad frame rather than a lab one.

    Included because the single-property variants are diagnostic but optimistic:
    a real dawn capture of a distant bird is blurred *and* dark *and* compressed,
    and errors from those do not simply add up.
    """
    out = distant(img, rng)
    out = motion_blur(out, rng)
    out = low_light(out, rng)
    return jpeg_lossy(out, rng)


VARIANTS = {
    "distant": distant,
    "off_center": off_center,
    "motion_blur": motion_blur,
    "low_light": low_light,
    "backlit": backlit,
    "sensor_soft": sensor_soft,
    "occluded": occluded,
    "jpeg_lossy": jpeg_lossy,
    "field_combo": field_combo,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--variant", action="append", choices=sorted(VARIANTS),
                    help="only build this variant (repeatable)")
    ap.add_argument("--force", action="store_true", help="rebuild existing files")
    args = ap.parse_args()

    root = Path(args.root)
    clean = root / "clean"
    if not clean.is_dir():
        print(f"No clean set at {clean} — run scripts/build_eval_set.py first",
              file=sys.stderr)
        return 1

    sources = sorted(clean.rglob("*.jpg"))
    if not sources:
        print(f"No photos under {clean}", file=sys.stderr)
        return 1

    wanted = args.variant or sorted(VARIANTS)
    print(f"{len(sources)} clean photos -> {len(wanted)} variants\n")

    for name in wanted:
        fn = VARIANTS[name]
        written = skipped = 0
        for src in sources:
            dest = root / name / src.parent.name / src.name
            if dest.exists() and not args.force:
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                out = fn(im.convert("RGB"), _rng(name, src))
            out.save(dest, format="JPEG", quality=JPEG_QUALITY)
            written += 1
        note = f", {skipped} already present" if skipped else ""
        print(f"  {name:12} {written:4d} written{note}")

    print(f"\nDone -> {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
