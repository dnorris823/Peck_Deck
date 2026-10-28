from abc import ABC, abstractmethod


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
    async def next_event(self) -> float:
        """Block until the next trigger fires. Returns asyncio monotonic timestamp."""
        ...
