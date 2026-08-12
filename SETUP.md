# Pi Setup Checklist

Manual steps required before `raspberry_pi_code` runs end-to-end.
Work through these in order — later sections depend on earlier ones.

---

## 1. Environment file

1. Copy `.env.example` to `.env` in this directory.
2. Fill in `BACKEND_URL` with the gaming PC's local IP and port (e.g., `http://192.168.1.100:8000`).
3. Leave `DEVICE_TOKEN` alone — `scripts/provision_device.py` writes it, and rewrites it
   whenever it goes stale. See §6.
4. Set `TRIGGER_TYPE` (`pir` or `ir_beam`) and `TRIGGER_GPIO_PIN` once hardware is decided.

---

## 2. ML model assets

Both files must exist before Tier 1 classification works.
Default paths (relative to project root):

| File | Default path |
|---|---|
| INatVision TFLite model | `machine_learning/INatVision_Small_2_fact256_8bit.tflite` |
| Taxonomy CSV | `machine_learning/taxonomy.csv` |

**taxonomy.csv requirements:**
- Must have columns `common_name`, `genus`, `species` (case-insensitive headers).
- Row order must match the model's output indices exactly — row 0 = class 0, row 1 = class 1, etc.
- Verify this against the INatVision model documentation or the source repo where you downloaded the `.tflite` from.

If the files are stored elsewhere, override the paths in `.env`:
```
MODEL_PATH=/absolute/path/to/model.tflite
TAXONOMY_PATH=/absolute/path/to/taxonomy.csv
```

---

## 3. Pi hardware

- [ ] Raspberry Pi 5 physically assembled.
- [ ] Camera module connected (ribbon cable seated, locked).
- [ ] Trigger peripheral (PIR or IR beam break) wired to a GPIO pin and GND.
  - PIR: signal wire → GPIO pin, pull-down resistor recommended (the code configures `PUD_DOWN`).
  - IR beam: receiver output → GPIO pin (the code configures `PUD_UP` and listens for FALLING edge).
- [ ] Battery pack connected and charged.
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
pip install RPi.GPIO tflite-runtime

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

It signs in as the owner, matches `DEVICE_NAME` against `GET /devices`, registers the
device if it isn't there, checks the token is accepted with a heartbeat, and writes
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

## 7. GPU inference server (Tier 2, blocked until M3)

- The gaming PC's GPU inference server (`inference_server/`) is not built yet (Milestone 3).
- Set `TIER_PREFERENCE=local` in `.env` to skip Tier 2 until the server exists.
- Once the server is running, update `INFERENCE_SERVER_URL` in `.env`.

---

## 8. Network

- [ ] Pi connected to home WiFi (run `sudo raspi-config` → System → Wireless LAN).
- [ ] Gaming PC and Pi are on the same subnet.
- [ ] Gaming PC's firewall allows inbound TCP on port 8000 (backend) and 8001 (inference server).
- [ ] Confirm reachability: `ping <gaming-pc-ip>` from the Pi.

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
sudo systemctl enable peck-deck
sudo systemctl start peck-deck
sudo journalctl -u peck-deck -f   # live logs
```

---

## Quick reference — what blocks what

| Feature | Blocked by |
|---|---|
| Tier 1 local classification | Model + taxonomy files (§2) |
| Posting sightings to backend | Backend built + device token (§6) |
| Tier 2 GPU classification | GPU inference server built (§7) |
| Tier 3 cloud classification | Backend built, Claude API key configured in backend `.env` |
| Offline sync | Backend reachable (§6, §8) |
| Auto-start on boot | systemd unit installed (§9) |
