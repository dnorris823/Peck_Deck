from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..bird_crop import Box


@dataclass(frozen=True)
class TriggerEvent:
    """One visit, of a bird or another animal.

    ``box`` is what the trigger saw, in fractions of the full frame. The
    pipeline crops the capture to it for the classifiers. None means no box.
    ``class_id`` is the COCO class that fired, None for a motion capture.
    ``trigger`` is "detector", or "motion" for the motion fallback.
    """

    time: float  # asyncio monotonic timestamp
    box: Box | None = None
    class_id: int | None = None
    trigger: str = "detector"



class TriggerBase(ABC):
    """Abstract trigger interface."""

    @abstractmethod
    async def __aenter__(self) -> "TriggerBase":
        ...

    @abstractmethod
    async def __aexit__(self, *args) -> None:
        ...

    @abstractmethod
    async def next_event(self) -> TriggerEvent:
        """Block until the next trigger fires."""
        ...
