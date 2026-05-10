"""Peck Deck — Raspberry Pi service entry point.

Run from the project root:
    python -m raspberry_pi_code.main

Or after `pip install -e .`:
    peck-deck-pi
"""

import asyncio
import logging
import sys

from .config import Config
from .pipeline import Pipeline
from .trigger.base import TriggerBase


def _build_trigger(config: Config) -> TriggerBase:
    if config.trigger_type == "ir_beam":
        from .trigger.ir_beam_trigger import IRBeamTrigger
        return IRBeamTrigger(config.trigger_gpio_pin)
    from .trigger.pir_trigger import PIRTrigger
    return PIRTrigger(config.trigger_gpio_pin)


async def _sync_loop(pipeline: Pipeline, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await pipeline.sync_offline_queue()
        except Exception:
            logging.getLogger(__name__).exception("Sync loop error")


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(__name__)

    config = Config()
    pipeline = Pipeline(config)
    pipeline.setup()

    trigger = _build_trigger(config)
    logger.info(
        "Peck Deck Pi starting  [tier=%s  trigger=%s  pin=%d  debounce=%.0fs]",
        config.tier_preference,
        config.trigger_type,
        config.trigger_gpio_pin,
        config.debounce_seconds,
    )

    async with trigger:
        sync_task = asyncio.create_task(
            _sync_loop(pipeline, config.sync_interval_seconds),
            name="offline-sync",
        )
        try:
            while True:
                await trigger.next_event()
                asyncio.create_task(
                    pipeline.handle_trigger(),
                    name="capture",
                )
        finally:
            sync_task.cancel()
            await asyncio.gather(sync_task, return_exceptions=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
