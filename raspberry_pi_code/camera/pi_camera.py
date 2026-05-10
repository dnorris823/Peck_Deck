import asyncio
import logging
from pathlib import Path

from .base import CameraBase

logger = logging.getLogger(__name__)


class PiCamera(CameraBase):
    """picamera2-based still image capture.

    Falls back to a solid-colour dummy JPEG when picamera2 is not available
    (e.g., during development on a non-Pi machine).
    """

    def __init__(self, width: int = 1920, height: int = 1080, quality: int = 90):
        self._width = width
        self._height = height
        self._quality = quality
        self._cam = None

    async def __aenter__(self) -> "PiCamera":
        try:
            from picamera2 import Picamera2

            self._cam = Picamera2()
            cfg = self._cam.create_still_configuration(
                main={"size": (self._width, self._height)}
            )
            self._cam.configure(cfg)
            self._cam.start()
            logger.info("Camera started at %dx%d", self._width, self._height)
        except ImportError:
            logger.warning("picamera2 not available — captures will produce dummy images")
        return self

    async def __aexit__(self, *args) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam.close()
            self._cam = None

    async def capture(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._cam is not None:
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._cam.capture_file(str(output_path)),
            )
        else:
            await asyncio.get_running_loop().run_in_executor(
                None, self._write_dummy, output_path
            )
        logger.debug("Captured: %s", output_path)
        return output_path

    def _write_dummy(self, output_path: Path) -> None:
        from PIL import Image

        Image.new("RGB", (self._width, self._height), color=(80, 120, 80)).save(
            output_path, "JPEG", quality=self._quality
        )
