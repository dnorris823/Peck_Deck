# Peck Deck — Raspberry Pi Hardware Test Plan

**Target device:** Raspberry Pi 5 Model B Rev 1.0 (8 GB)
**Generated:** 2026-07-17 · branch `dnorris_claude`
**Purpose:** Exercise every piece of hardware physically available on this Pi and
tie each test back to what the Peck Deck bird-feeder pipeline actually needs
(camera capture → trigger → local/remote classification → upload).

---

## 1. Detected Hardware Inventory

| Component | Detected | Detail | Relevance to Peck Deck |
|---|---|---|---|
| Board | ✅ | Raspberry Pi 5 Model B Rev 1.0 | Pi runtime host |
| CPU | ✅ | 4× Cortex-A76 @ 2.4 GHz (aarch64) | Local inference (Tier 1) |
| RAM | ✅ | 7.9 GiB total, ~6 GiB available | Model + image buffers |
| Storage | ✅ | 58 GB SD (`mmcblk0`), 16 % used | Image cache, logs, models |
| **Camera** | ✅ | **IMX708 Wide (Camera Module 3)** `/base/...i2c@88000/imx708@1a` | **Primary capture sensor** |
| GPIO | ✅ | `gpiochip0` (pinctrl-rp1, 54 lines) via RP1 | Trigger peripheral (PIR / IR beam) |
| I2C | ✅ | buses 6/10/13/14 present; user in `i2c` group | Optional sensors, camera control |
| SPI | ✅ | user in `spi` group | Optional peripherals |
| WiFi | ✅ | `wlan0` UP @ 192.168.4.104/22 | Tier 2/3 offload + upload |
| Ethernet | ⚠️ | `eth0` present but DOWN (no cable) | Alt. LAN path |
| USB | ✅ | Logitech USB receiver on bus 001 | Dev keyboard/mouse only |
| Audio | ✅ | HDMI out (vc4hdmi0/1); no capture device | PRD "audio detection" = future, no mic present |
| Temp/Power | ⚠️ | 73.6 °C idle, `throttled=0x80000` (soft temp limit *has occurred*) | Thermal headroom under inference load |

### Software / library status (found on device)

| Library | Status | Impact |
|---|---|---|
| `picamera2` | ✅ import OK | Camera pipeline usable now |
| `RPi.GPIO` | ✅ import OK | **Verify it's the `rpi-lgpio` shim** — stock RPi.GPIO fails at runtime on Pi 5's RP1 |
| `lgpio`, `gpiozero` | ✅ import OK | Preferred GPIO path on Pi 5 |
| `numpy`, `PIL` | ✅ import OK | Image handling |
| `cv2` (OpenCV) | ➖ not installed — **not needed** | No Pi code imports it; downgraded from blocker |
| `tflite_runtime` | ✅ **RESOLVED** — 2.14.0 in `.venv` | Tier 1 runtime works (verified end-to-end) |
| `machine_learning/*.tflite` model | ⚠️ real model still absent; **stand-in built** | Tier 1 path exercisable now; real model TBD (see §2) |
| `RPi.GPIO` backend | ✅ **RESOLVED** — is `rpi-lgpio` shim v0.6 | lgpio-backed; works on Pi 5 RP1 (was blocker #4) |
| CLI: `rpicam-still/hello`, `i2cdetect`, `gpioset/get`, `pinctrl`, `vcgencmd` | ✅ present | Used by tests below |

> **Environment note:** ML work runs in a `.venv` created with
> `python3 -m venv --system-site-packages .venv` so `picamera2` (a system apt
> package) stays visible alongside pip-installed `tflite-runtime`. **Do not install
> a numpy ≥ 2 into this venv** — it breaks `picamera2`'s `simplejpeg` C-extension,
> which is compiled against the system numpy 1.24.2. (TensorFlow was installed only
> to author the stand-in model, then removed for exactly this reason.)

---

## 2. Known Blockers — status

### ✅ Resolved (2026-07-17)

1. **`tflite_runtime` not installed** → **RESOLVED.** Installed `tflite-runtime==2.14.0`
   (cp311 aarch64) into `.venv`. Tier-1 inference verified on a live camera capture.
2. **No `.tflite` model in the repo** → **UNBLOCKED for testing.** The real
   `INatVision_Small_2_fact256_8bit.tflite` was never committed to any branch — it is an
   external asset. To exercise the Tier-1 code path now, a **stand-in** model was generated:
   - `machine_learning/build_standin_model.py` — authors a valid uint8 224×224 → N-class
     TFLite model (N = rows in `taxonomy.csv`). Needs TensorFlow *only to build*; the Pi
     runtime uses `tflite_runtime`.
   - `machine_learning/stand_in_smoketest_224_uint8.tflite` — the generated model (gitignored).
   - `machine_learning/taxonomy.csv` — 20 common backyard species (tracked; replace with the
     real taxonomy when the real model lands).
   - `raspberry_pi_code/smoke_test_tier1.py` — drives PiCamera + TFLiteClassifier end-to-end.
   - **Verified run:** capture 302 KB JPEG in ~900 ms · model load 8 ms · inference ~40 ms avg
     (10 runs) · argmax→taxonomy mapping OK.
   - **Still TODO for production:** obtain the real INatVision model + its matching taxonomy;
     point `MODEL_PATH` / `TAXONOMY_PATH` (or `config.py`) at them. Labels from the stand-in
     are meaningless by design.
3. **`cv2` missing** → **NOT A BLOCKER.** No Pi code imports OpenCV; removed from scope.
4. **RP1 GPIO caveat** → **RESOLVED.** `import RPi.GPIO` on this Pi resolves to the
   **`rpi-lgpio` shim v0.6** (lgpio-backed), which supports the Pi 5's RP1. `RPI_INFO`
   correctly reports `Pi 5 Model B / BCM2712 / 8GB`. The project's `import RPi.GPIO` edge
   detection will work as written; `gpiozero`/`lgpio` are also available as alternatives.

### ⛔ Cannot resolve in software (hardware not present)

5. **No physical trigger peripheral wired** (no PIR / IR-beam on the header). Trigger tests
   (Suite C) run as (C1–C3) loopback/simulated GPIO now; (C4) real-sensor when one is attached.
6. **No microphone / audio-capture device** → PRD's audio-based detection stays out of scope
   for this hardware pass.

### ⚠️ Findings surfaced while unblocking

7. **Tier-1 did not dequantize uint8 model output.** `tier1_tflite.py` used the raw output
   tensor as `confidence`; with an 8-bit model that yielded a 0–255 integer, not a 0–1
   probability (observed `confidence=16.0`), making the `confidence_threshold=0.5` gate
   meaningless. ✅ **FIXED** — `_infer` now applies the output tensor's `quantization`
   (scale/zero-point) when the model is integer-quantized; verified `confidence=0.066`
   (proper probability) on the stand-in model.
8. **Runs hot:** SoC held **80–82 °C** during capture+inference and `throttled=0x80000`
   (soft-temp-limit) was already set at idle. Validate active cooling before sustained load
   testing (Suites B5 / E4).

---

## 3. Test Suites

Each test lists: **Goal · How · Pass criteria**. Ordered from lowest-risk/no-wiring to
peripheral-dependent. Prefer running from `raspberry_pi_code/` where noted so imports resolve.

### Suite A — Board / System Health (no wiring)
- **A1 Identity & firmware** — `cat /proc/device-tree/model`, `vcgencmd version`.
  *Pass:* reports Pi 5 Model B, recent firmware.
- **A2 Memory** — `free -h`; optional `stress-ng --vm 2 --vm-bytes 1G -t 30s` if installed.
  *Pass:* no OOM, swap not thrashing.
- **A3 Storage health & speed** — `df -h /`; write test
  `dd if=/dev/zero of=/tmp/peck_io bs=8M count=64 oflag=dsync` then `rm`.
  *Pass:* >20 MB/s sustained write, no I/O errors in `dmesg`.
- **A4 Thermal baseline** — record `vcgencmd measure_temp` and `vcgencmd get_throttled`.
  *Pass:* idle < 80 °C; note current soft-limit flag (`0x80000`) as a **pre-existing** cooling concern.

### Suite B — Camera (IMX708) — **highest project value**
- **B1 Enumeration** — `rpicam-hello --list-cameras`.
  *Pass:* `imx708_wide` listed with expected modes (already ✅).
- **B2 Still capture (native tool)** —
  `rpicam-still -o /tmp/peck_test.jpg --width 1920 --height 1080 -t 800 -n`.
  *Pass:* valid non-black JPEG; check `file` + size > 50 KB.
- **B3 Capture via project code** — from `raspberry_pi_code/`, drive `camera/pi_camera.py`
  `PiCamera(1920,1080,90).capture(...)` in a short asyncio harness.
  *Pass:* real image written (not the dummy-JPEG fallback path); log says "Camera started".
- **B4 Resolution/quality matrix** — capture at 1920×1080 and full 4608×2592.
  *Pass:* both succeed; record capture latency (feeds trigger→capture timing budget).
- **B5 Sustained/repeat capture** — 20 captures in a loop, monitor temp.
  *Pass:* no dropped frames / camera stalls; temp stays < 85 °C.

### Suite C — GPIO & Trigger Peripheral
- **C0 GPIO backend sanity** — confirm which library actually drives pins:
  `python3 -c "import RPi.GPIO as G; print(G.RPI_INFO if hasattr(G,'RPI_INFO') else G.__file__)"`
  and prefer `gpiozero`/`lgpio` on Pi 5. *Pass:* identify a working backend for RP1.
- **C1 Output toggle (safe pin)** — use an unused BCM pin (e.g. 17, the project default),
  drive it with `pinctrl set 17 op dh` / `dl` or `gpioset gpiochip0 17=1/0`, read back with
  `pinctrl get 17`. *Pass:* readback matches commanded level.
- **C2 Input + internal pull** — `gpioget --bias=pull-up gpiochip0 17` vs `--bias=pull-down`.
  *Pass:* reads 1 with pull-up, 0 with pull-down (no external wiring).
- **C3 Loopback edge detection** — jumper an output pin to input pin `17`; drive edges and
  confirm `trigger/pir_trigger.py` (RISING) and `trigger/ir_beam_trigger.py` (FALLING)
  enqueue events via their `next_event()`. *Pass:* each edge produces exactly one event
  (debounce/`bouncetime=200` respected).
- **C4 Real sensor (only if hardware attached)** — wire PIR or IR-beam to pin 17 per
  `config.py` (`TRIGGER_TYPE`, `TRIGGER_GPIO_PIN`); wave hand / break beam.
  *Pass:* `main.py` pipeline logs a trigger and proceeds to capture.

### Suite D — I2C / SPI (optional peripherals)
- **D1 Bus scan** — `i2cdetect -y <bus>` for exposed header bus.
  *Pass:* command runs; document any external device addresses (none expected currently).
- **D2 SPI presence** — `ls /dev/spidev*`; enable via `raspi-config`/overlay if a SPI
  peripheral is added later. *Informational.*

### Suite E — Local ML Inference (Tier 1) — **blocked, see §2**
- **E1 Runtime install check** — `pip install tflite-runtime` (or `ai-edge-litert`); import.
- **E2 Model load** — load `INatVision_Small_2_fact256_8bit.tflite` (once fetched);
  inspect input/output tensor shapes.
- **E3 Inference on B2 image** — run one classification, map index→species via `taxonomy.csv`.
  *Pass:* returns a plausible label + confidence; record per-image latency + CPU temp under load.
- **E4 Thermal-under-load** — loop E3 ×50 while logging `vcgencmd measure_temp`.
  *Pass:* no throttling that breaks real-time budget; note if active cooling is required.

### Suite F — Connectivity / Offload Path
- **F1 WiFi link** — `iwconfig wlan0` / `ping -c4 <gateway>`; already UP.
  *Pass:* stable, low loss.
- **F2 Tier 2 reachability** — `curl` `INFERENCE_SERVER_URL` `/health` (from `config.py`).
  *Pass:* reachable if the RTX 5080 server is on the LAN (else document as offline).
- **F3 Backend reachability + upload** — `curl` `BACKEND_URL`; dry-run a `POST /sightings`
  multipart with a B2 image via `raspberry_pi_code/api_client.py`.
  *Pass:* auth handshake works or fails cleanly with a logged reason.

### Suite G — End-to-End Pipeline Dry Run
- **G1** — run `raspberry_pi_code/main.py` with `TIER_PREFERENCE=local`, trigger via C3
  loopback, capture with the real camera. *Pass:* trigger → capture → (classify or graceful
  Tier-1 skip) → cache/upload attempt, all logged with no unhandled exceptions.

---

## 4. Suggested Execution Order

1. **A** (system health) → **B** (camera, the money feature) → **F1** (WiFi) — all runnable now, no wiring.
2. **C0–C2** GPIO sanity (no wiring), then **D1** bus scan.
3. Resolve §2 blockers → **E** (Tier 1 ML), **F2/F3** (offload/upload).
4. **C3** loopback, then **C4/G1** once a physical trigger sensor is wired.

## 5. Deliverables per run
- Pass/fail table, captured sample images (B2/B3), latency numbers (B4, E3),
  and a thermal log (A4/B5/E4) — the last is important given the **soft-temp-limit flag is
  already set at idle**, which suggests cooling should be validated before load testing.

---

## 6. Bring-up run — 2026-07-24 (branch `phase-4-hardware-bringup`)

First session with the Pi *and* the RTX 5080 both live on the LAN
(Pi `192.168.4.104` wlan0 ↔ PC `192.168.4.28` eth0, same /22).

### Results

| Suite | Result |
|---|---|
| A1/A4 Board + thermal | ✅ Pi 5 Model B, 8 GB. Idle **59.3 °C**, **64.2 °C** under capture+inference — much cooler than the 80–82 °C seen on 2026-07-17. |
| B1 Camera enumeration | ✅ `imx708_wide`, modes to 4608×2592. |
| B3 Capture via project code | ✅ Real sensor image, ~300 KB @1920×1080 in **~1.0 s** (not the dummy fallback). |
| C0 GPIO backend | ✅ `rpi-lgpio` shim; `RPI_INFO` reports Pi 5 / BCM2712 / 8GB. |
| C1 Output toggle (BCM17) | ✅ drive high → reads `hi`; drive low → reads `lo`. Pin restored to `ip pn`. |
| C2 Internal pulls (BCM17) | ✅ pull-up → `hi`, pull-down → `lo`. |
| C3/C4 Trigger | ⛔ still blocked — nothing wired to the header. |
| E2/E3 Tier 1 inference | ✅ load 6 ms, inference **38.7 ms avg** (37.1–41.1, n=10). Stand-in model. |
| F1 WiFi | ✅ 1.9–5.0 ms RTT to the PC. |
| F2 Tier 2 reachability | ✅ `/health` → `{"status":"ok","model_ready":true}`. No firewall rule was needed. |
| F3 Backend upload | ✅ real multipart `POST /sightings` from the Pi → row 135 in Postgres, **300,518-byte** camera JPEG stored as `bytea`, `delayed=false`, offline queue empty. |
| G1 Tier chain dry run | ✅ capture → Tier 1 (0.05) → Tier 2 (0.25) → Tier 3 (503, no API key) → best-effort → upload. |
| Image round trip | ✅ `GET /sightings/135/image` with a user JWT returns the same 300,518 bytes (`FF D8 FF E0`); unauthenticated request correctly 401s. |

**GPU host:** torch 2.11.0+cu128, CUDA 12.8, RTX 5080, capability **(12, 0)**,
arch list includes `sm_120`. Model loads on `cuda` with the 20-entry taxonomy.

### ⚠️ Defects found and fixed this session

9. **Tier fallback ignored confidence entirely.** `Pipeline._classify` advanced
   only when a tier returned `None`, so a 0.05-confidence Tier 1 answer won
   outright and Tier 2/3 were never consulted. `config.confidence_threshold`
   was read by no code at all. ✅ **FIXED** — falls through on low confidence,
   retaining the best sub-threshold result as a fallback.
10. **`python -m inference_server` did not work** — the command the docs give.
    No `__main__.py` existed. ✅ **FIXED.**
11. **`TAXONOMY_PATH` default resolved outside the repo** — it was CWD-relative
    (`../machine_learning/...`) but the package must run from the repo root.
    ✅ **FIXED** — anchored to the repo root.
12. **Tier 3 stalled the pipeline for 60 s when the backend was down**, longer
    than the 30 s trigger debounce, and logged a full stack trace for the
    routine offline case. ✅ **FIXED** — `tier3_request_timeout` (25 s default)
    plumbed through from config; `asyncio.TimeoutError` handled like Tier 2.
    Verified on hardware: 60.9 s → 25.3 s.
13. **The API container could never start.** `backend/Dockerfile` flattened
    `backend/` into `/app` and ran `uvicorn main:app`, but `main.py` imports its
    siblings relatively (`from .auth.guards import ...`), so it crashed on boot
    with *"attempted relative import with no known parent package"*. Both test
    suites import `backend.main` from the repo root, so neither ever exercised
    the container — `docker compose up`, the documented way to run the stack,
    was broken. ✅ **FIXED** — copies into `/app/backend` and runs
    `uvicorn backend.main:app`.

### Environment notes

- Two checkouts exist on the Pi. **`~/coding/Peck_Deck` is the live one**
  (has the Python 3.11 `.venv` with `tflite-runtime`); `~/peck_deck/Peck_Deck`
  is an abandoned copy stuck at an early commit — don't work in it.
- `aiohttp` was missing from the Pi venv and had to be installed; it is required
  for both Tier 2 and the backend client. numpy stayed at the system 1.24.2.
- On the PC, `uv` manages a Python 3.12 venv at `.venv`. The system Python is
  3.14, which torch has no wheels for.

### Still blocking a real field test

1. **Real model weights** — both tiers are stand-ins; every label so far is
   meaningless by construction. Biggest remaining gap.
2. **A physical trigger sensor** (or a jumper for the C3 loopback test).
3. **Backend + Postgres on the PC** with a real device token, so `POST /sightings`
   and Tier 3 can be exercised at all.

---
*Notes captured from live probing of this device on 2026-07-17, updated with the
2026-07-24 bring-up run. Update the blocker list in §2 as libraries/models/sensors
are added.*
