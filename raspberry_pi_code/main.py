"""Peck Deck — Raspberry Pi service entry point.

Run from the project root:
    python -m raspberry_pi_code.main

Or after `pip install -e .`:
    peck-deck-pi
"""

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable

from .api_client import BackendClient, UploadOutcome
from .camera.base import CameraBase
from .camera.pi_camera import PiCamera
from .config import ENV_PATH, Config
from .live import RTSP_PUBLISH_URL
from .live.address import LiveUrl
from .live.demand import LiveDemandServer
from .pipeline import Pipeline
from .trigger.base import TriggerBase
from .wifi import read_signal


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
            class_ids=config.animal_class_ids,
        ),
        motion_threshold=config.camera_motion_threshold,
        quiet_gap_seconds=config.camera_visit_gap_seconds,
        analysis_fps=config.camera_analysis_fps,
        roi=config.camera_roi,
        motion_capture=config.camera_motion_capture,
        motion_capture_seconds=config.camera_motion_capture_seconds,
    )


def _build_live(config: Config, camera: PiCamera) -> LiveDemandServer | None:
    """The live demand server, or None when LIVE_ENABLED is false."""
    if not config.live_enabled:
        return None
    return LiveDemandServer(
        config.live_demand_socket,
        start=lambda: camera.start_live(RTSP_PUBLISH_URL, config.live_bitrate),
        stop=camera.stop_live,
    )


def _no_live_url() -> str | None:
    return None


def _live_url_source(config: Config, live: LiveDemandServer | None) -> Callable[[], str | None]:
    """What the heartbeat reports as live_url.

    Nothing when live video is off, or when the demand socket did not open,
    because then no viewer could start the encoder.
    """
    if live is None or not live.listening:
        return _no_live_url
    return LiveUrl(config.live_url, config.backend_url)


async def _sync_loop(pipeline: Pipeline, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await pipeline.sync_offline_queue()
        except Exception:
            logging.getLogger(__name__).exception("Sync loop error")


def _no_signal() -> str | None:
    return None


def _no_trigger_age() -> float | None:
    return None


async def _heartbeat_loop(
    client: BackendClient,
    interval: float,
    live_url: Callable[[], str | None] = _no_live_url,
    power_source: str | None = None,
    signal: Callable[[], str | None] = _no_signal,
    trigger_age: Callable[[], float | None] = _no_trigger_age,
) -> None:
    """Report to the backend every `interval` seconds, starting now.

    Logs only when the result changes, so a backend that is down for an hour
    costs one warning, not sixty. Nothing here may stop capture.

    ``live_url`` runs in a worker thread each beat, because deriving it looks up
    the route to the backend, which may resolve a host name. ``signal`` reads a
    file, so it runs there too. ``trigger_age`` is the camera trigger's
    seconds since its last analysis tick, for the backend's feed check.
    """
    logger = logging.getLogger(__name__)
    last_ok: bool | None = None
    while True:
        try:
            url = await asyncio.to_thread(live_url)
            wifi = await asyncio.to_thread(signal)
            outcome = await client.heartbeat(
                live_url=url, power_source=power_source, signal=wifi,
                trigger_age_seconds=trigger_age(),
            )
        except Exception:
            logger.exception("Heartbeat error")
            outcome = UploadOutcome.RETRY
        ok = bool(outcome)
        if ok and last_ok is False:
            logger.info("Heartbeat reaching the backend again")
        elif not ok and last_ok is not False:
            logger.warning("Heartbeat failed (%s); the station will show offline", outcome.value)
        last_ok = ok
        await asyncio.sleep(interval)


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(__name__)

    config = Config()
    if not ENV_PATH.exists():
        # Every setting is on its default, so BACKEND_URL points at an address
        # that is probably not the gaming PC and every upload will queue.
        logger.warning(
            "No %s. Running on defaults. A .env anywhere else is ignored, "
            "so move it here", ENV_PATH,
        )

    # One camera for the whole run. picamera2 allows one owner per camera, and
    # the camera trigger streams from it all the time, so the trigger and the
    # pipeline share this instance. Nothing else may open the camera.
    camera = PiCamera(config.image_width, config.image_height, config.jpeg_quality,
                      fps=config.live_fps)
    trigger = _build_trigger(config, camera)
    live = _build_live(config, camera)

    pipeline = Pipeline(config, camera=camera)
    pipeline.setup()

    logger.info(
        "Peck Deck Pi starting  [tier=%s  trigger=camera  visit_gap=%.0fs  "
        "motion=%.3f  detect=%.2f  fps=%.1f  roi=%s  live=%s  power=%s]",
        config.tier_preference,
        config.camera_visit_gap_seconds,
        config.camera_motion_threshold,
        config.camera_detection_threshold,
        config.camera_analysis_fps,
        ",".join(f"{v:g}" for v in config.camera_roi),
        "on" if live is not None else "off",
        config.power_source,
    )

    # The live server exits first, so the encoder stops before the camera does.
    async with camera, trigger, live or contextlib.nullcontext():
        background = [
            asyncio.create_task(
                _sync_loop(pipeline, config.sync_interval_seconds),
                name="offline-sync",
            ),
            # Classify and upload run here, one capture at a time, so a slow
            # Tier 2 never holds the camera from the next visit.
            asyncio.create_task(pipeline.run_classifier(), name="classify"),
            asyncio.create_task(
                _heartbeat_loop(
                    BackendClient(config.backend_url, config.device_token,
                                  config.backend_connect_timeout),
                    config.heartbeat_interval_seconds,
                    _live_url_source(config, live),
                    config.power_source,
                    read_signal,
                    trigger.tick_age,
                ),
                name="heartbeat",
            ),
        ]
        try:
            while True:
                event = await trigger.next_event()
                asyncio.create_task(
                    pipeline.handle_trigger(event.box, trigger=event.trigger),
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
