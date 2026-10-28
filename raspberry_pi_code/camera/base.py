from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np


class CameraBase(ABC):
    """Abstract camera interface.

    One instance owns the camera for the whole run. The capture pipeline and the
    camera trigger share it, because picamera2 allows one owner per camera.
    """

    @abstractmethod
    async def __aenter__(self) -> "CameraBase":
        ...

    @abstractmethod
    async def __aexit__(self, *args) -> None:
        ...

    @abstractmethod
    async def capture(self, output_path: Path) -> Path:
        """Capture a JPEG still image to output_path and return the path."""
        ...

    @abstractmethod
    async def grab_gray(self) -> np.ndarray | None:
        """Return a small 2-D uint8 greyscale frame for the motion check.

        Returns None when the camera is not streaming.
        """
        ...

    @abstractmethod
    async def grab_rgb(self) -> np.ndarray | None:
        """Return an (h, w, 3) uint8 RGB frame for the bird detector.

        Returns None when the camera is not streaming.
        """
        ...
