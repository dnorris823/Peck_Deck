"""Small JPEG thumbnails for the gallery grids.

A capture is about 300 KB. A grid tile is a few hundred pixels wide, so the
grids fetch a thumbnail instead. The upload path and the backfill share
``make_thumbnail``.
"""
import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger("peckdeck.sightings")

# Long side, in pixels. A 130 px tile on a 3x phone screen needs about 400.
THUMBNAIL_SIZE = 400
THUMBNAIL_QUALITY = 80


def make_thumbnail(image_bytes: bytes) -> bytes | None:
    """A JPEG of ``image_bytes`` scaled to ``THUMBNAIL_SIZE`` on the long side.

    Returns None if Pillow cannot decode the bytes. It never raises, because it
    runs on the Pi's upload path, and a sighting without a thumbnail still
    serves its full image in the thumbnail's place.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # For a JPEG, draft() makes libjpeg decode at 1/2, 1/4 or 1/8 scale.
            # That is most of the speed-up, and the backfill decodes every row.
            img.draft("RGB", (THUMBNAIL_SIZE * 2, THUMBNAIL_SIZE * 2))
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
            return out.getvalue()
    except Exception:
        logger.warning("could not make a thumbnail from %d image bytes", len(image_bytes), exc_info=True)
        return None
