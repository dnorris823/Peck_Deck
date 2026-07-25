#!/usr/bin/env python
"""Render the Peck Deck app icons for the PWA manifest (FLEDGE Phase 7).

    python scripts/generate_pwa_icons.py

Writes PNGs into ``frontend/public/icons/``. They are committed, so this only
needs re-running when the brand mark changes.

The mark is the same bird-in-a-circle path the sidebar draws (`Shell.jsx`), kept
here as a literal SVG path string so the two can be compared by eye rather than
redrawn from scratch. Pillow has no SVG support and adding a rasterizer
(cairosvg → cairo → GTK on Windows) for one build step isn't worth it, so the
handful of path commands the mark uses (M/L/C/Z) are flattened to a polygon here
and drawn at 8x, then downsampled — which antialiases far better than Pillow's
own path drawing.

Needs Pillow (`backend/requirements-dev.txt`), like the simulator's placeholder
images. Nothing at runtime imports this.
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "frontend" / "public" / "icons"

# Brand tokens — must match :root in frontend/src/styles.css.
INK = (28, 38, 32)
PAPER = (243, 237, 224)
FOREST = (45, 74, 54)

# The sidebar's brand mark, in a 24x24 viewBox (frontend/src/Shell.jsx).
BIRD_PATH = (
    "M5 14 C 5 10 8 7 12 7 L 16 5 L 18 7 L 17 9 C 19 10 19 13 17 14 "
    "L 17 17 L 14 17 L 12 19 L 11 16 L 9 17 L 9 14 Z"
)
VIEWBOX = 24
# Sampling density per cubic segment. 24 is smooth well past 512px because the
# canvas is rendered at 8x before being downsampled.
CURVE_STEPS = 24
SUPERSAMPLE = 8


def _cubic(p0, p1, p2, p3, steps=CURVE_STEPS):
    """Sample a cubic bezier, excluding the start point (already emitted)."""
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        ))
    return out


def flatten_path(path: str) -> list[tuple[float, float]]:
    """Turn an M/L/C/Z path into a single closed polygon.

    Only these three commands are supported — that is all the mark uses, and a
    general SVG path parser here would be dead code pretending to be a library.
    """
    tokens = re.findall(r"[MLCZmlcz]|-?\d*\.?\d+", path)
    points: list[tuple[float, float]] = []
    i = 0
    cmd = None
    while i < len(tokens):
        token = tokens[i]
        if token.upper() in "MLCZ":
            cmd = token.upper()
            i += 1
            if cmd == "Z":
                continue
        if cmd in ("M", "L"):
            points.append((float(tokens[i]), float(tokens[i + 1])))
            i += 2
        elif cmd == "C":
            nums = [float(n) for n in tokens[i:i + 6]]
            points.extend(_cubic(
                points[-1], (nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])
            ))
            i += 6
        else:  # pragma: no cover — unreachable for BIRD_PATH
            raise ValueError(f"Unsupported path command: {cmd!r}")
    return points


def render(size: int, *, bird_scale: float, ring: bool) -> Image.Image:
    """One icon: full-bleed ink field, paper bird, optional forest hairline ring.

    ``bird_scale`` is the fraction of the canvas the *drawn mark* spans — fitted
    to the path's bounding box, not to the 24x24 viewBox, which the mark only
    fills about 60% of. Maskable icons get a smaller value so the mark survives
    being cropped to a circle by the launcher (safe zone is the middle 80%).
    """
    big = size * SUPERSAMPLE
    img = Image.new("RGB", (big, big), INK)
    draw = ImageDraw.Draw(img)

    if ring:
        inset = big * 0.055
        draw.ellipse(
            [inset, inset, big - inset, big - inset],
            outline=FOREST, width=max(1, int(big * 0.012)),
        )

    path_points = flatten_path(BIRD_PATH)
    xs = [p[0] for p in path_points]
    ys = [p[1] for p in path_points]
    scale = (big * bird_scale) / max(max(xs) - min(xs), max(ys) - min(ys))

    def place(x: float, y: float) -> tuple[float, float]:
        return (
            (big - (max(xs) - min(xs)) * scale) / 2 + (x - min(xs)) * scale,
            (big - (max(ys) - min(ys)) * scale) / 2 + (y - min(ys)) * scale,
        )

    draw.polygon([place(x, y) for x, y in path_points], fill=PAPER)

    # The eye — a small ink dot at (15, 9) in the viewBox, as in Shell.jsx.
    eye_r = big * 0.017
    ex, ey = place(15, 9)
    draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=INK)

    return img.resize((size, size), Image.LANCZOS)


ICONS = [
    # (filename, size, bird scale, ring)
    ("icon-192.png", 192, 0.58, True),
    ("icon-512.png", 512, 0.58, True),
    # Maskable: no ring (the launcher supplies the shape) and a tighter mark so
    # a circular crop can't clip a wing.
    ("icon-maskable-512.png", 512, 0.52, False),
    # iOS never rounds transparency for you and ignores maskable, so this is the
    # plain opaque tile Safari puts on the home screen.
    ("apple-touch-icon-180.png", 180, 0.62, False),
    ("icon-32.png", 32, 0.72, False),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, size, bird_scale, ring in ICONS:
        path = OUT_DIR / name
        render(size, bird_scale=bird_scale, ring=ring).save(path, optimize=True)
        print(f"wrote {path.relative_to(ROOT)} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
