"""Placeholder capture images for the device simulator (FLEDGE Phase 5).

The simulator has to send *something* as the sighting image — `POST /sightings`
is a multipart upload and the gallery renders whatever lands in `bytea`. Rather
than commit a bank of binary JPEGs, the bank is drawn at run time from each
species' own palette, so every species gets a distinct, recognisable plate and
the gallery reads as a gallery instead of twelve copies of one file.

Drawing needs Pillow, which is a *dev* dependency (`backend/requirements-dev.txt`)
— the API container never imports this module, so it stays lean. Pillow is
already a Raspberry Pi dependency, so it is not a new tool in this repo.

Images are cached per palette: a live run posts one sighting every few seconds
for hours, and re-encoding the same twelve plates each time would be pure waste.
"""
from __future__ import annotations

import io
import math
import random

# Roughly a 3:2 field-guide plate. Small on purpose — the point is a plausible
# ~30-80 KB JPEG, not a photograph.
_SIZE = (640, 428)
_QUALITY = 82

_cache: dict[tuple[str, ...], bytes] = {}


class PillowMissing(RuntimeError):
    """Raised with an actionable message when Pillow isn't installed."""


def _require_pillow():
    try:
        from PIL import Image, ImageDraw  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise PillowMissing(
            "The simulator draws its placeholder images with Pillow, which is a "
            "dev dependency. Install it with:\n"
            "    pip install -r backend/requirements-dev.txt\n"
            "(or just: pip install Pillow)"
        ) from exc
    from PIL import Image, ImageDraw

    return Image, ImageDraw


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def render_plate(palette: list[str], *, seed: int = 0) -> bytes:
    """Draw a stylized JPEG "capture" from a species palette.

    A vertical wash between two palette colors, a soft vignette, and an
    off-centre bird-ish silhouette in the third. Deterministic for a given
    palette + seed, so repeated runs produce byte-identical images.
    """
    Image, ImageDraw = _require_pillow()

    colors = [_rgb(c) for c in palette] or [(122, 138, 140)]
    while len(colors) < 3:
        colors.append(_mix(colors[0], (255, 255, 255), 0.5))
    top, bottom, mark = colors[0], colors[1], colors[2]

    w, h = _SIZE
    img = Image.new("RGB", (w, h))
    px = img.load()

    rng = random.Random(seed)
    # Vertical wash plus faint diagonal grain. The grain is not decoration: a
    # perfectly flat gradient compresses to a few hundred bytes, which is not a
    # useful stand-in for a ~50 KB camera frame.
    for y in range(h):
        row = _mix(top, bottom, y / (h - 1))
        for x in range(w):
            grain = int(3 * math.sin((x + y * 0.7) * 0.09))
            px[x, y] = tuple(max(0, min(255, c + grain)) for c in row)

    draw = ImageDraw.Draw(img, "RGBA")

    # Perch line, then a simple bird: tail, body, head, beak, eye.
    cx = w * (0.44 + rng.random() * 0.12)
    cy = h * (0.54 + rng.random() * 0.06)
    r = h * 0.17
    body = (*mark, 240)
    draw.line([(0, cy + r * 1.3), (w, cy + r * 1.5)],
              fill=(*_mix(mark, (0, 0, 0), 0.45), 120), width=4)
    draw.polygon([(cx - r * 1.1, cy - r * 0.3), (cx - r * 2.4, cy + r * 0.7),
                  (cx - r * 1.0, cy + r * 0.5)], fill=(*mark, 200))
    draw.ellipse([cx - r * 1.25, cy - r, cx + r * 1.25, cy + r], fill=body)
    draw.ellipse([cx + r * 0.55, cy - r * 1.6, cx + r * 1.6, cy - r * 0.55], fill=body)
    draw.polygon([(cx + r * 1.55, cy - r * 1.18), (cx + r * 2.2, cy - r * 1.02),
                  (cx + r * 1.55, cy - r * 0.86)],
                 fill=(*_mix(mark, (0, 0, 0), 0.4), 245))
    draw.ellipse([cx + r * 1.02, cy - r * 1.32, cx + r * 1.2, cy - r * 1.14],
                 fill=(*_mix(mark, (0, 0, 0), 0.75), 255))

    # Radial vignette — darkens smoothly toward the corners so the plate reads
    # as a captured frame rather than flat artwork.
    mask = Image.radial_gradient("L").resize((w, h))
    shade = Image.new("RGB", (w, h), _mix(bottom, (0, 0, 0), 0.55))
    img = Image.composite(shade, img, mask.point(lambda v: int(v * 0.55)))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_QUALITY)
    return buf.getvalue()


def plate_for(palette: list[str], *, seed: int = 0) -> bytes:
    """Cached :func:`render_plate` — the bank the simulator draws from."""
    key = (str(seed), *palette)
    if key not in _cache:
        _cache[key] = render_plate(palette, seed=seed)
    return _cache[key]
