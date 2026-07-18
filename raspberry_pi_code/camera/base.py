from abc import ABC, abstractmethod
from pathlib import Path


class CameraBase(ABC):
    """Abstract camera interface."""

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
