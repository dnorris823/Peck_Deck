import asyncio
import logging

from .base import TriggerBase

logger = logging.getLogger(__name__)


class IRBeamTrigger(TriggerBase):
    """IR beam-break trigger (FALLING edge on receiver GPIO pin).

    Wire the receiver output to the configured pin with a pull-up resistor.
    The beam being broken pulls the pin LOW, generating the FALLING edge.
    """

    def __init__(self, pin: int):
        self._pin = pin
        self._queue: asyncio.Queue[float] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._gpio = None

    async def __aenter__(self) -> "IRBeamTrigger":
        self._loop = asyncio.get_running_loop()
        try:
            import RPi.GPIO as GPIO

            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                self._pin,
                GPIO.FALLING,
                callback=self._callback,
                bouncetime=200,
            )
            logger.info("IR beam trigger active on GPIO BCM pin %d", self._pin)
        except ImportError:
            logger.warning("RPi.GPIO not available — IR beam trigger is simulated (no events will fire)")
        return self

    async def __aexit__(self, *args) -> None:
        if self._gpio is not None:
            self._gpio.remove_event_detect(self._pin)
            self._gpio.cleanup(self._pin)
            self._gpio = None

    def _callback(self, channel: int) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                self._loop.time(),
            )

    async def next_event(self) -> float:
        return await self._queue.get()
