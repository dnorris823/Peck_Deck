from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..bird_crop import Box


@dataclass(frozen=True)
class TriggerEvent:
    """One bird visit.

    ``box`` is the bird the trigger saw, in fractions of the full frame. The
    pipeline crops the capture to it for the classifiers. None means no box.
    """

    time: float  # asyncio monotonic timestamp
    box: Box | None = None



class TriggerBase(ABC):
    """Abstract trigger interface.

    ``debounces_itself`` is True for a trigger that applies its own repeat rule.
    ``main.py`` then sets the pipeline's debounce to 0, so one rule decides.
    """

    debounces_itself: bool = False

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
