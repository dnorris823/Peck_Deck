import asyncio
import logging
from pathlib import Path

import numpy as np

from .base import CameraBase

logger = logging.getLogger(__name__)

# Size of the lores stream that feeds the motion check. Small on purpose: the
# check runs several times a second for as long as the service is up.
LORES_SIZE = (320, 240)


class PiCamera(CameraBase):
    """One long-lived picamera2 camera with two streams.

    picamera2 allows one owner per camera, and the camera trigger needs the
    camera streaming all the time. So `main.py` opens this once and hands it to
    both the trigger and the pipeline.

    * main: full-size stills for `capture()`, and RGB frames for the detector.
    * lores: small YUV420 frames. The Y plane is the greyscale motion frame.

    An asyncio lock serialises every request, so a capture and a trigger frame
    grab never reach picamera2 at the same time.

    Falls back to a solid-colour dummy JPEG when picamera2 is not available
    (e.g., during development on a non-Pi machine). In that case `grab_gray()`
    and `grab_rgb()` return None, so the camera trigger fires nothing.
    """

    def __init__(self, width: int = 1920, height: int = 1080, quality: int = 90):
        self._width = width
        self._height = height
        self._quality = quality
        self._cam = None
        self._lores_size = LORES_SIZE
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PiCamera":
        try:
            from picamera2 import Picamera2
        except ImportError:
            logger.warning("picamera2 not available — captures will produce dummy images")
            return self

        cam = Picamera2()
        # BGR888 is picamera2's name for an array in [R, G, B] order, which is
        # what the detector wants. The still configuration keeps the
        # high-quality denoise the per-capture camera used before.
        cfg = cam.create_still_configuration(
            main={"size": (self._width, self._height), "format": "BGR888"},
            lores={"size": LORES_SIZE, "format": "YUV420"},
            # One buffer stalls the stream while a frame is being copied out.
            buffer_count=2,
        )
        cam.configure(cfg)
        cam.start()
        self._cam = cam
        # picamera2 may align the requested size. Use what it settled on.
        self._lores_size = tuple(cam.camera_configuration()["lores"]["size"])
        logger.info(
            "Camera started: main %dx%d, lores %dx%d",
            self._width, self._height, *self._lores_size,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam.close()
            self._cam = None

    async def capture(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            if self._cam is not None:
                await asyncio.to_thread(self._cam.capture_file, str(output_path))
            else:
                await asyncio.to_thread(self._write_dummy, output_path)
        logger.debug("Captured: %s", output_path)
        return output_path

    async def grab_gray(self) -> np.ndarray | None:
        if self._cam is None:
            return None
        async with self._lock:
            yuv = await asyncio.to_thread(self._cam.capture_array, "lores")
        # A YUV420 array is (h * 3/2, stride). The first h rows are the Y
        # plane, and columns past w are row padding.
        w, h = self._lores_size
        return yuv[:h, :w]

    async def grab_rgb(self) -> np.ndarray | None:
        if self._cam is None:
            return None
        async with self._lock:
            return await asyncio.to_thread(self._cam.capture_array, "main")

    def _write_dummy(self, output_path: Path) -> None:
        from PIL import Image

        Image.new("RGB", (self._width, self._height), color=(80, 120, 80)).save(
            output_path, "JPEG", quality=self._quality
        )
