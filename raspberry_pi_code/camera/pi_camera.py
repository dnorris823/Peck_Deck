import asyncio
import logging
from pathlib import Path

import numpy as np

from .base import CameraBase

logger = logging.getLogger(__name__)

# Size of the lores stream. It feeds both the live encoder and the motion check.
LORES_SIZE = (1280, 720)
# The motion check takes every 4th pixel of the lores Y plane each way, so it
# still sees 320x180 and keeps the cost it had on a 320x240 stream.
MOTION_SUBSAMPLE = 4


class PiCamera(CameraBase):
    """One long-lived picamera2 camera with two streams.

    picamera2 allows one owner per camera, and the camera trigger needs the
    camera streaming all the time. So `main.py` opens this once and hands it to
    both the trigger and the pipeline.

    * main: full-size stills for `capture()`, and RGB frames for the detector.
    * lores: 1280x720 YUV420. It feeds the live encoder, and its Y plane,
      subsampled, is the greyscale motion frame.

    An asyncio lock serialises every request, so a capture and a trigger frame
    grab never reach picamera2 at the same time. The live encoder does not take
    the lock. picamera2 feeds it every lores frame from its own thread, so
    captures and frame grabs carry on while it runs.

    Falls back to a solid-colour dummy JPEG when picamera2 is not available
    (e.g., during development on a non-Pi machine). In that case `grab_gray()`
    and `grab_rgb()` return None, so the camera trigger fires nothing.
    """

    def __init__(self, width: int = 1920, height: int = 1080, quality: int = 90,
                 fps: int = 30):
        self._width = width
        self._height = height
        self._quality = quality
        self._fps = fps
        self._cam = None
        self._encoder = None
        self._lores_size = LORES_SIZE
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PiCamera":
        try:
            from picamera2 import Picamera2
            from libcamera import controls
        except ImportError:
            logger.warning("picamera2 not available — captures will produce dummy images")
            return self

        cam = Picamera2()
        frame_us = int(1_000_000 / self._fps)
        # A video configuration, so the sensor runs at a steady frame rate the
        # live encoder can use. BGR888 is picamera2's name for an array in
        # [R, G, B] order, which is what the detector wants. The video
        # configuration defaults to fast denoise. Ask for the high-quality
        # denoise the still configuration used, so stills look as they did.
        cfg = cam.create_video_configuration(
            main={"size": (self._width, self._height), "format": "BGR888"},
            lores={"size": LORES_SIZE, "format": "YUV420"},
            controls={
                "FrameDurationLimits": (frame_us, frame_us),
                "NoiseReductionMode": controls.draft.NoiseReductionModeEnum.HighQuality,
            },
            # Spare buffers, so copying a frame out does not stall the encoder.
            buffer_count=4,
        )
        cam.configure(cfg)
        cam.start()
        self._cam = cam
        # picamera2 may align the requested size. Use what it settled on.
        self._lores_size = tuple(cam.camera_configuration()["lores"]["size"])
        logger.info(
            "Camera started: main %dx%d, lores %dx%d at %d fps",
            self._width, self._height, *self._lores_size, self._fps,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._cam is not None:
            try:
                self.stop_live()
            except Exception:
                logger.warning("Live encoder failed to stop at shutdown", exc_info=True)
            self._cam.stop()
            self._cam.close()
            self._cam = None

    def start_live(self, url: str, bitrate: int) -> None:
        """Encode the lores stream as H.264 and publish it to ``url`` over RTSP.

        Blocking. Raises when the camera is not streaming or the encoder will
        not start. The Pi 5 has no hardware H.264 encoder, so this is libx264
        in picamera2's encoder thread, with its ultrafast preset and zerolatency
        tune.
        """
        if self._cam is None:
            raise RuntimeError("the camera is not streaming")
        if self._encoder is not None:
            return
        from picamera2.encoders import LibavH264Encoder
        from picamera2.outputs import PyavOutput

        # A keyframe every second, so a new viewer sees a picture within one.
        encoder = LibavH264Encoder(bitrate=bitrate, framerate=self._fps, iperiod=self._fps)
        output = PyavOutput(url, format="rtsp")
        output.error_callback = lambda exc: logger.warning("Live RTSP output failed: %s", exc)
        self._cam.start_encoder(encoder, output, name="lores")
        self._encoder = encoder

    def stop_live(self) -> None:
        """Stop the live encoder. Does nothing when it is not running."""
        encoder, self._encoder = self._encoder, None
        if encoder is not None and self._cam is not None:
            self._cam.stop_encoder([encoder])

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
        return yuv[:h:MOTION_SUBSAMPLE, :w:MOTION_SUBSAMPLE]

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
