"""Live video from the feeder camera.

MediaMTX on the Pi does the WebRTC work. When the first viewer arrives it runs
``python -m raspberry_pi_code.live_demand``, which connects to the service's
demand socket. The service encodes while at least one such connection is open
and publishes to MediaMTX over RTSP on localhost. See SETUP.md, "Live video".
"""

# Where the encoder publishes. MediaMTX listens for RTSP on localhost only.
RTSP_PUBLISH_URL = "rtsp://127.0.0.1:8554/feeder"
