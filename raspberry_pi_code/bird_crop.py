"""The bird's box, from the detector to the classifiers.

The camera is the 120° wide IMX708, so a bird fills a small part of each frame.
Both classifier tiers expect a bird that fills the image. Tier 1 squashes the
whole frame to 224 x 224, and Tier 2's transform keeps only a centre square. On
2026-10-28 Tier 1 called a clear house finch "Background (92%)" because the dark
room filled the frame. So the classifiers get a square crop around the box, and
the sighting keeps the full frame.

A box is (x, y, width, height) in fractions of the frame, the same form as
``CAMERA_ROI``.
"""

from pathlib import Path

Box = tuple[float, float, float, float]


def to_frame(box: Box, roi: Box) -> Box:
    """Map a box in fractions of the ``roi`` crop to fractions of the full frame."""
    bx, by, bw, bh = box
    rx, ry, rw, rh = roi
    return (rx + bx * rw, ry + by * rh, bw * rw, bh * rh)


def square_around(
    frame_w: int, frame_h: int, box: Box, margin: float
) -> tuple[int, int, int, int]:
    """Pixel edges (left, top, right, bottom) of a square crop around ``box``.

    The square's side is the box's longer side plus ``margin`` of it on each
    side. It is centred on the box. At a frame edge the square slides inside
    the frame rather than shrinks, so the classifier still gets a square. It
    shrinks only when it is larger than the frame's shorter side.
    """
    x, y, w, h = box
    side = max(w * frame_w, h * frame_h) * (1 + 2 * margin)
    side = int(round(min(max(side, 1.0), frame_w, frame_h)))
    cx = (x + w / 2) * frame_w
    cy = (y + h / 2) * frame_h
    left = min(max(int(round(cx - side / 2)), 0), frame_w - side)
    top = min(max(int(round(cy - side / 2)), 0), frame_h - side)
    return left, top, left + side, top + side


def write_crop(src: Path, dst: Path, box: Box, margin: float, quality: int) -> tuple[int, int]:
    """Save the square crop of ``src`` around ``box`` to ``dst`` as a JPEG.

    Returns the crop's (width, height). Blocking: call it through
    ``asyncio.to_thread``.
    """
    from PIL import Image

    with Image.open(src) as img:
        edges = square_around(img.width, img.height, box, margin)
        out = img.crop(edges).convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "JPEG", quality=quality)
    return out.size
