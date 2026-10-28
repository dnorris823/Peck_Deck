"""Peck Deck — Raspberry Pi service entry point.

Run from the project root:
    python -m raspberry_pi_code.main

Or after `pip install -e .`:
    peck-deck-pi
"""

import asyncio
import logging
import sys

from .camera.base import CameraBase
from .camera.pi_camera import PiCamera
from .config import Config
from .pipeline import Pipeline
from .trigger.base import TriggerBase

TRIGGER_TYPES = ("camera", "pir", "ir_beam")


def _build_trigger(config: Config, camera: CameraBase) -> TriggerBase:
    """Build the trigger that TRIGGER_TYPE names. Raises ValueError on any other value.

    An unknown value refuses to start. Falling back to some default trigger
    would run a feeder that never fires, with nothing in the log to say why.
    """
    if config.trigger_type == "camera":
        from .trigger.bird_detector import BirdDetector
        from .trigger.camera_trigger import CameraTrigger

        return CameraTrigger(
            camera,
            BirdDetector(config.detector_model_path, config.camera_detection_threshold),
            motion_threshold=config.camera_motion_threshold,
            quiet_gap_seconds=config.camera_visit_gap_seconds,
            analysis_fps=config.camera_analysis_fps,
        )
    if config.trigger_type == "ir_beam":
        from .trigger.ir_beam_trigger import IRBeamTrigger
        return IRBeamTrigger(config.trigger_gpio_pin)
    if config.trigger_type == "pir":
        from .trigger.pir_trigger import PIRTrigger
        return PIRTrigger(config.trigger_gpio_pin)
    raise ValueError(
        f"Unknown TRIGGER_TYPE {config.trigger_type!r}. "
        f"Expected one of: {', '.join(TRIGGER_TYPES)}"
    )


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

    # One camera for the whole run. picamera2 allows one owner per camera, and
    # the camera trigger streams from it all the time, so the trigger and the
    # pipeline share this instance. Nothing else may open the camera.
    camera = PiCamera(config.image_width, config.image_height, config.jpeg_quality)
    trigger = _build_trigger(config, camera)

    # The camera trigger's visit gap is its repeat rule. Keep the pipeline's
    # debounce out of the way, or a second visit inside DEBOUNCE_SECONDS would
    # be dropped by a rule the trigger knows nothing about.
    debounce = 0.0 if trigger.debounces_itself else config.debounce_seconds
    pipeline = Pipeline(config, camera=camera, debounce_seconds=debounce)
    pipeline.setup()

    if config.trigger_type == "camera":
        logger.info(
            "Peck Deck Pi starting  [tier=%s  trigger=camera  visit_gap=%.0fs  "
            "motion=%.3f  detect=%.2f  fps=%.1f]",
            config.tier_preference,
            config.camera_visit_gap_seconds,
            config.camera_motion_threshold,
            config.camera_detection_threshold,
            config.camera_analysis_fps,
        )
    else:
        logger.info(
            "Peck Deck Pi starting  [tier=%s  trigger=%s  pin=%d  debounce=%.0fs]",
            config.tier_preference,
            config.trigger_type,
            config.trigger_gpio_pin,
            debounce,
        )

    async with camera, trigger:
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
