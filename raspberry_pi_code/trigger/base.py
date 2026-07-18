from abc import ABC, abstractmethod


class TriggerBase(ABC):
    """Abstract trigger peripheral interface."""

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
