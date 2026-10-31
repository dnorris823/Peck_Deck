# Pi Setup Checklist

Manual steps required before `raspberry_pi_code` runs end-to-end.
Work through these in order — later sections depend on earlier ones.

---

## 1. Environment file

1. Copy `.env.example` to `.env` in this directory.
2. Fill in `BACKEND_URL` with the gaming PC's local IP and port (e.g., `http://192.168.1.100:8000`).
3. Leave `DEVICE_TOKEN` alone — `scripts/provision_device.py` writes it, and rewrites it
   whenever it goes stale. See §6.
4. Leave `TRIGGER_TYPE` at its default, `camera`. The camera trigger watches the feed
   and needs no extra hardware. It is the only trigger. Any other value stops the
   service at start with an error.

---

## 2. ML model assets

Both files must exist before Tier 1 classification works. The taxonomy is
committed. Fetch the model from the project root:

```bash
python scripts/fetch_models.py
```

Default paths (relative to project root):

| File | Default path |
|---|---|
| Tier 1 TFLite model (AIY `birds_V1`) | `machine_learning/aiy_birds_V1_224_uint8.tflite` |
| Taxonomy CSV | `machine_learning/taxonomy.csv` |

**taxonomy.csv requirements:**
- Must have columns `common_name`, `genus`, `species` (case-insensitive headers).
- Row order must match the model's output indices exactly — row 0 = class 0, row 1 = class 1, etc.
- `scripts/build_taxonomy.py` generates it from the model's label map. Regenerate it, never hand-edit it.

If the files are stored elsewhere, override the paths in `.env`:
```
MODEL_PATH=/absolute/path/to/model.tflite
TAXONOMY_PATH=/absolute/path/to/taxonomy.csv
```

The camera trigger needs its own model, a COCO bird detector. The same
`fetch_models.py` run writes `machine_learning/efficientdet_lite0_detection.tflite` and checks its
digest. Override the path with `DETECTOR_MODEL_PATH`. Without the file, the service
still starts, logs a warning, and the camera trigger fires no events.

---

## 3. Pi hardware

- [ ] Raspberry Pi 5 physically assembled.
- [ ] Camera module connected (ribbon cable seated, locked).
- [ ] No trigger peripheral. The camera is the trigger.
- [ ] Mains power at the window.
- [ ] Camera port enabled in `raspi-config` → Interface Options → Camera.

---

## 4. Raspberry Pi OS + Python environment

Run these on the Pi:

```bash
# System packages
sudo apt update
sudo apt install -y python3-pip python3-venv python3-picamera2

# Project virtual environment (from project root)
python3 -m venv .venv
source .venv/bin/activate

# Pi-specific packages
pip install tflite-runtime

# Project Python dependencies
pip install -r raspberry_pi_code/requirements.txt
```

> **tflite-runtime note:** If `pip install tflite-runtime` fails (arm64 wheel missing),
> install TensorFlow Lite from the official Pi wheel:
> `pip install https://github.com/google-coral/pycoral/releases/download/...`
> or use `pip install tensorflow` as a fallback (heavier but works).

---

## 5. Cache directory

The Pi needs a writable directory for the rolling image cache and offline queue.
The default is `/var/lib/peck_deck/cache`. Create it and set permissions:

```bash
sudo mkdir -p /var/lib/peck_deck/cache
sudo chown pi:pi /var/lib/peck_deck/cache
```

Or override `CACHE_DIR` in `.env` to use a path the Pi user already owns (e.g., `~/peck_deck_cache`).

---

## 6. Backend — device token

The Pi authenticates to the backend with a device-specific token. **Don't paste it by
hand** — the Pi provisions itself:

```bash
python scripts/provision_device.py
```

It signs in as the owner, matches `DEVICE_NAME` against `GET /devices`, and reads the
token from the owner-only `GET /devices/{id}/token`. It registers the device if it
isn't there, since `POST /devices` returns the token once. Then it checks the token is accepted with a heartbeat, and writes
`DEVICE_TOKEN` into `raspberry_pi_code/.env` — leaving every other key alone. It is
idempotent, so it is safe to run against a fresh, reseeded or already-healthy database.
Credentials come from the environment, never from `argv`. See §9 for the systemd wiring
that runs it on every start, and where the credentials live.

Why not by hand: `device_guard` is a plain equality match on the token with no expiry
or rotation, so a stale token is indistinguishable from a wrong one — 401 forever, with
the offline queue filling silently behind it. Tokens go stale because `backend/seed.py`
mints a fresh one on every seed, so wiping the database volume orphans whatever the Pi
holds. Re-provisioning has to be cheap, and hand-transcribing a 43-character urlsafe
blob over SSH is not.

A missing token is a hard blocker for posting sightings and for Tier 2 / Tier 3.
Tier 1 local classification and offline queuing work without it.

---

## 7. GPU inference server (Tier 2)

- Tier 2 is the main classifier. It runs on the gaming PC from `inference_server/`.
  `CONTRIBUTING.md` has the commands and the cu128 PyTorch note for the RTX 5080.
- Set `INFERENCE_SERVER_URL` in `.env` to the gaming PC's LAN address, port 8001.

### Tier order

`TIER_PREFERENCE` in `raspberry_pi_code/.env` sets the order the Pi tries the tiers in.
A tier that fails, or answers below its threshold, hands the capture to the next one.

| Value | Order | Calls Claude |
|---|---|---|
| `gpu` (default) | Tier 2, then Tier 1 | No |
| `auto` | Tier 1, then Tier 2, then Tier 3 | Yes |
| `cloud` | Tier 3, then Tier 2, then Tier 1 | Yes |
| `local` | Tier 1 only | No |

Any other value refuses to start.

If every tier fails, the Pi still uploads the capture, or queues it. The sighting
has species "Unknown" and tier `none`.

### Turn Tier 3 on

Tier 3 is off by default. To turn it on:

1. Set `ANTHROPIC_API_KEY` in the backend's `.env` on the gaming PC, and restart the
   backend. Without it, the backend's `POST /classify` returns 503, and the Pi moves
   on to the next tier.
2. Set `TIER_PREFERENCE=auto` or `TIER_PREFERENCE=cloud` in `raspberry_pi_code/.env`,
   and restart the Pi service.

Each Tier 3 call is a paid Claude API call. With `auto`, the Pi calls Claude only
when Tier 1 and Tier 2 both fall short. With `cloud`, it calls Claude for every
capture.

---

## 8. Network

- [ ] Pi connected to home WiFi (run `sudo raspi-config` → System → Wireless LAN).
- [ ] Gaming PC and Pi are on the same subnet.
- [ ] The gaming PC has a fixed LAN address, so the Pi's `.env` never goes stale. Set a DHCP
      reservation on the router. On the eero, use the eero app: Settings → Network settings →
      Reservations & port forwarding → Add a reservation. The PC shows up under its Windows
      computer name. In this setup the reserved address is `192.168.4.55`.
- [ ] `BACKEND_URL` and `INFERENCE_SERVER_URL` in the Pi's `.env` use that address, on ports
      8000 and 8001.
- [ ] Confirm reachability from the Pi, with the backend and Tier 2 running on the gaming PC:

  ```bash
  curl -m 5 http://<gaming-pc-ip>:8000/ready
  curl -m 5 http://<gaming-pc-ip>:8001/health
  ```

  Both should answer in milliseconds. A timeout usually means the server is not running.
  Windows Firewall drops packets to a closed port without a reply, so a stopped server looks
  the same as a blocked one. Check the server first. Add an inbound rule for TCP 8000 and 8001
  on the Private profile only if a running server still times out. On 2026-10-28 no rule was
  needed.

---

## 9. Run the service

From the project root on the Pi (with `.venv` active):

```bash
python -m raspberry_pi_code.main
```

**To run as a systemd service** (auto-start on boot):

```ini
# /etc/systemd/system/peck-deck.service
[Unit]
Description=Peck Deck Pi Service
After=network-online.target
Wants=network-online.target
# Bound the restart loop explicitly. A refused token makes the service exit
# non-zero, which re-runs the pre-step, which may fail the same way — without
# these it is a tight crash loop on systemd's defaults.
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
User=pi
WorkingDirectory=/home/pi/peck_deck
# Owner credentials for the pre-step. Root-owned 0600 — systemd reads it before
# dropping to User=pi, so the pi user never needs to be able to read it. The
# leading `-` means a missing file does not block startup.
EnvironmentFile=-/etc/peck_deck/owner.env
# Re-provision the device token on every start. The leading `-` is load-bearing:
# a Pi booting while the gaming PC is off must still start and capture into the
# offline queue, which is the queue's whole purpose.
ExecStartPre=-/home/pi/peck_deck/.venv/bin/python scripts/provision_device.py
ExecStart=/home/pi/peck_deck/.venv/bin/python -m raspberry_pi_code.main
Restart=on-failure
RestartSec=10
# Creates /run/peck-deck, owned by User=, for the live video demand socket.
# systemd removes it when the service stops.
RuntimeDirectory=peck-deck

[Install]
WantedBy=multi-user.target
```

MediaMTX serves live video. It runs as the same user as `peck-deck`, so its
`live_demand` helper can open the demand socket. Install it as in §11 first.

```ini
# /etc/systemd/system/mediamtx.service
[Unit]
Description=MediaMTX live video for Peck Deck
After=network-online.target
Wants=network-online.target

[Service]
User=pi
# runOnDemand in the config runs .venv/bin/python from here.
WorkingDirectory=/home/pi/peck_deck
# Read credentials and addresses. Root-owned 0600. No leading `-`: without
# the file the unit fails, rather than run with no reader able to log in.
EnvironmentFile=/etc/peck_deck/mediamtx.env
ExecStart=/opt/mediamtx/mediamtx /home/pi/peck_deck/raspberry_pi_code/live/mediamtx.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The credential file the pre-step reads:

```bash
sudo install -d -m 700 /etc/peck_deck
sudo tee /etc/peck_deck/owner.env >/dev/null <<'EOF'
PECK_OWNER_EMAIL=you@example.com
PECK_OWNER_PASSWORD=your-owner-password
DEVICE_NAME=Windowsill
EOF
sudo chmod 600 /etc/peck_deck/owner.env
```

**This is deliberately not the Pi's `.env`** — that file is what `provision_device.py`
rewrites and what the pipeline reads, and the owner account can mint users
(`POST /users` is owner-only). Keeping the account-minting credential in a separate
root-owned file is the least this can be, given the escalation was accepted knowingly.

Run it by hand once before enabling the service, to see what it matched:

```bash
sudo -E env $(sudo cat /etc/peck_deck/owner.env | xargs) .venv/bin/python scripts/provision_device.py
```

It prints `matched existing device 'Windowsill' (id 4)` or `registered new device …`.
Read that line — a `DEVICE_NAME` typo otherwise registers a *second* device silently,
and sightings split across two rows that both look healthy in the app.

```bash
sudo systemctl enable peck-deck mediamtx
sudo systemctl start peck-deck mediamtx
sudo journalctl -u peck-deck -f   # live logs
```

---

## 10. Desk test the camera trigger

Run the service by hand with the camera pointed at an empty desk:

```bash
python -m raspberry_pi_code.main
```

1. Check the start-up log. It must show `Camera started`, `Bird detector loaded`,
   and `Camera trigger active`. A `will fire no events` warning means picamera2 or
   the detector model is missing.
2. Leave the frame empty for a minute. Nothing must fire.
3. Wave a hand through the frame. Nothing must fire.
4. Hold a printed or on-screen bird photo up to the camera. The log must show
   `Bird detected (score ...). Starting a new visit`, then a capture.
5. Keep the photo there. No second capture must follow while it stays in view.
6. Take it away for more than `CAMERA_VISIT_GAP_SECONDS` (15 s by default), then
   show it again. That is a new visit and must capture again.

If the photo never fires, lower `CAMERA_DETECTION_THRESHOLD`. If the hand fires,
raise it. Record what you changed and why.

### Point the detector at the feeder

The 120 degree camera sees far more than the feeder. The detector shrinks
whatever it gets to 320x320, so a bird in the full 1920x1080 frame is only a few
pixels wide. Set `CAMERA_ROI` to the feeder's region, as fractions of the frame:
`x,y,width,height`. For example, `0.25,0.25,0.5,0.5` is the middle half. The
detector runs on that crop of the main stream, and the motion check uses the same
region of the lores frame. Motion outside it no longer wakes the detector.

Unset means the full frame. A value that is not four numbers, or that does not
fit inside the frame, stops the service at start with a `CAMERA_ROI` error. The
detector squashes the crop to a square, so a crop close to square distorts the
bird least. The captured image is not cropped.

### The classifiers see the bird, not the room

The detector reports where the bird is. The pipeline crops each capture to a
square around that box before Tier 1 and Tier 2 classify it. The square's side is
the box's longer side plus `CLASSIFY_CROP_MARGIN` of it on each side, 0.25 by
default. At a frame edge the square slides inside the frame. The sighting still
stores the full frame. The log line `Classifying a 300x300 crop around the bird
box` shows the crop size for each visit. If the crop fails, or the detector gave
no box, the classifiers get the full frame.

To find the numbers, stop the service, because the camera has one owner. Take a
still with `rpicam-still -o roi.jpg`. Read the feeder's corners in pixels, then
divide by the image width and height. The fractions do not depend on the image
size, because every stream sees the same field of view.

### Detector threads

`DETECTOR_THREADS` sets the TFLite interpreter's thread count. The default 4
uses all four Pi 5 cores. On the Pi 5, one detection took 138 ms on one thread
and 63 ms on four. The startup log line `Bird detector loaded` shows the count.

## 11. Live video

The web app shows the feeder live over WebRTC. MediaMTX on the Pi does the
WebRTC work. The backend relays the browser's offer to it, as described in
`docs/live-video.md`. The video goes from the Pi to the browser directly.

```
viewer arrives ─▶ MediaMTX runs `python -m raspberry_pi_code.live_demand`
live_demand ─▶ connects to LIVE_DEMAND_SOCKET ─▶ the Pi service starts the encoder
encoder ─▶ RTSP to 127.0.0.1:8554/feeder ─▶ MediaMTX ─▶ WebRTC to the browser
last viewer gone 10 s ─▶ MediaMTX stops live_demand ─▶ the service stops the encoder
```

The encoder is libx264 in picamera2, on the 1280x720 lores stream. The Pi 5 has
no hardware H.264 encoder. It runs only while someone watches.

### Install MediaMTX

The pinned version is **v1.21.3**. Check the download against the release's
checksum file.

```bash
V=v1.21.3
cd "$(mktemp -d)"
curl -fsSLO https://github.com/bluenviron/mediamtx/releases/download/$V/mediamtx_${V}_linux_arm64.tar.gz
curl -fsSLO https://github.com/bluenviron/mediamtx/releases/download/$V/checksums.sha256
grep linux_arm64 checksums.sha256 | sha256sum -c -
sudo install -d /opt/mediamtx
sudo tar -xzf mediamtx_${V}_linux_arm64.tar.gz -C /opt/mediamtx
/opt/mediamtx/mediamtx --version
```

### Config

The config is `raspberry_pi_code/live/mediamtx.yml`. It holds no secrets.

- Only RTSP and WebRTC are on. RTMP, HLS, SRT, MoQ, the API, metrics, pprof and
  playback are off.
- RTSP listens on `127.0.0.1:8554`, TCP only, for the Pi service.
- Anyone on localhost may publish to `feeder`. Nobody else may publish.
- Reading `feeder` needs the read user. The env file supplies its name and
  password. The committed placeholders match no request, so a missing env file
  locks every reader out.
- The one path, `feeder`, runs the `live_demand` helper on demand, with a 10 s
  start timeout and a 10 s close delay.

### Env file

MediaMTX reads `MTX_*` variables as overrides of the config. The read user is
the second entry of `authInternalUsers`, index 1. Checked on v1.21.3.

```bash
sudo install -d -m 700 /etc/peck_deck
sudo tee /etc/peck_deck/mediamtx.env >/dev/null <<'ENV'
# Must equal LIVE_READ_USER and LIVE_READ_PASSWORD in the backend .env.
MTX_AUTHINTERNALUSERS_1_USER=peck-live
MTX_AUTHINTERNALUSERS_1_PASS=a-long-random-password
# The Pi's LAN address. Add its Tailscale address after a comma, so live video
# also works away from home.
MTX_WEBRTCADDITIONALHOSTS=192.168.4.104
ENV
sudo chmod 600 /etc/peck_deck/mediamtx.env
```

MediaMTX also offers the address of every network interface, so the LAN and
Tailscale addresses reach the browser even without `MTX_WEBRTCADDITIONALHOSTS`.
Set it anyway, and give the Pi a DHCP reservation as in §8. The backend and the
browser both need the Pi's address to stay put.

Then install the unit from §9 and start it.

### Firewall ports

| Port | Who connects | Why |
|---|---|---|
| 8889/tcp | The gaming PC | WHEP signalling. The backend relays offers here. |
| 8189/udp | Every browser that watches | WebRTC media, once ICE completes. |
| 8554/tcp | Nobody off the Pi | RTSP publish. It listens on 127.0.0.1 only. |

Raspberry Pi OS has no firewall by default. If you add one, open the first two
on the LAN and on the Tailscale interface.

### Settings

| Setting | Default | What it does |
|---|---|---|
| `LIVE_ENABLED` | `true` | `false` opens no demand socket and sends no `live_url`, so the app shows no live view. |
| `LIVE_FPS` | `30` | Camera frame rate for every stream. It fixes the frame time, so it also caps the exposure time. |
| `LIVE_BITRATE` | `2000000` | H.264 bitrate in bits per second. |
| `LIVE_DEMAND_SOCKET` | `/run/peck-deck/live.sock` | The Unix socket `live_demand` connects to. Mode 0600, so only the service's user can start the encoder. |
| `LIVE_URL` | derived | Where the backend sends WHEP offers. Unset means `http://<lan-ip>:8889/feeder/whep`, with the Pi's address on the route to `BACKEND_URL`. The service works it out again on every heartbeat. |

The heartbeat sends `live_url` only when it is `http` or `https` on a private
IPv4 address: 10/8, 172.16/12, 192.168/16, or 100.64/10. The backend refuses
anything else with 400, and a refused heartbeat would show the station offline.
So the Pi drops such a URL and logs it once.

### Check it

```bash
systemctl is-active mediamtx
# No credentials: 401.
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/sdp' \
  --data 'v=0' http://<pi>:8889/feeder/whep
```

Then open the live view in the app. The service log shows `Live encoder
started` when the first viewer arrives, and `Live encoder stopped` 10 s after
the last one leaves. With no viewer, `top` shows the service at its idle CPU.

### Measured on the Pi 5

Camera Module 3 Wide, 2026-10-30. CPU is the service process, as a percentage
of one core. The Pi 5 has four.

| State | Camera fps | Service CPU |
|---|---|---|
| Old still configuration, no detector | 14.9 | 4% |
| Video configuration, no viewer | 30.0 | 8% |
| Encoder running | 30.0 | 50% |
| Encoder, and the detector on every tick | 30.0 | 151% |

A WHEP reader on the gaming PC received 30.0 fps at 1280x720. Its first frame
came 1.3 s after the offer. High-quality denoise holds 30 fps, so stills keep it.
In a dim room, stills come out darker than under the old configuration, because
the fixed 33 ms frame time caps the exposure.

The motion check now sees a 320x180 frame, every 4th pixel of the lores Y plane.
On an unchanged scene, no tick reached `CAMERA_MOTION_THRESHOLD`, as before.

---

## Quick reference — what blocks what

| Feature | Blocked by |
|---|---|
| Camera trigger | Detector model (§2), picamera2 (§4) |
| Tier 1 local classification | Model + taxonomy files (§2) |
| Posting sightings to backend | Backend built + device token (§6) |
| Tier 2 GPU classification | GPU inference server running on the gaming PC (§7) |
| Tier 3 cloud classification | Backend built, `ANTHROPIC_API_KEY` in backend `.env`, `TIER_PREFERENCE=auto` or `cloud` (§7) |
| Offline sync | Backend reachable (§6, §8) |
| Auto-start on boot | systemd unit installed (§9) |
| Live video | MediaMTX and its env file (§11), backend `LIVE_READ_*` set, `LIVE_ENABLED=true` |
