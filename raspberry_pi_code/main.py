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


def _build_trigger(config: Config, camera: CameraBase) -> TriggerBase:
    """Build the camera trigger. Raises ValueError if TRIGGER_TYPE names anything else.

    The camera is the only trigger. A stale `TRIGGER_TYPE=pir` in an old `.env`
    refuses to start. Running the camera trigger instead would hide the change.
    """
    if config.trigger_type != "camera":
        raise ValueError(
            f"Unknown TRIGGER_TYPE {config.trigger_type!r}. The only trigger is "
            "'camera'. The GPIO triggers were removed"
        )
    from .trigger.bird_detector import BirdDetector
    from .trigger.camera_trigger import CameraTrigger

    return CameraTrigger(
        camera,
        BirdDetector(
            config.detector_model_path,
            config.camera_detection_threshold,
            num_threads=config.detector_threads,
        ),
        motion_threshold=config.camera_motion_threshold,
        quiet_gap_seconds=config.camera_visit_gap_seconds,
        analysis_fps=config.camera_analysis_fps,
        roi=config.camera_roi,
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

    pipeline = Pipeline(config, camera=camera)
    pipeline.setup()

    logger.info(
        "Peck Deck Pi starting  [tier=%s  trigger=camera  visit_gap=%.0fs  "
        "motion=%.3f  detect=%.2f  fps=%.1f  roi=%s]",
        config.tier_preference,
        config.camera_visit_gap_seconds,
        config.camera_motion_threshold,
        config.camera_detection_threshold,
        config.camera_analysis_fps,
        ",".join(f"{v:g}" for v in config.camera_roi),
    )

    async with camera, trigger:
        background = [
            asyncio.create_task(
                _sync_loop(pipeline, config.sync_interval_seconds),
                name="offline-sync",
            ),
            # Classify and upload run here, one capture at a time, so a slow
            # Tier 2 never holds the camera from the next visit.
            asyncio.create_task(pipeline.run_classifier(), name="classify"),
        ]
        try:
            while True:
                event = await trigger.next_event()
                asyncio.create_task(
                    pipeline.handle_trigger(event.box),
                    name="capture",
                )
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
