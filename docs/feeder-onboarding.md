# Add a feeder at another house

This guide sets up a new Pi feeder at a house away from the gaming PC. The feeder
belongs to a user at that house. It uploads to the backend and Tier 2 on the
gaming PC over the tailnet.

`SETUP.md` is the full Pi reference. This guide covers the order of the steps,
and the parts that differ when the feeder is not on the gaming PC's LAN.

## How it connects

```
Pi at their house ── tailnet ──▶ gaming PC
                                 ├─ :8000 backend (uploads, heartbeat, provisioning)
                                 └─ :8001 Tier 2 (classification)
gaming PC ── tailnet ──▶ Pi :8889 and :8888 (live video relay)
```

The Pi uses the gaming PC's tailnet address, never a LAN address. A tailnet
address stays the same when either machine changes networks. Nothing at either
house needs a port forward or a firewall rule.

On 2026-10-31 both directions worked over the tailnet with no firewall change.
The home Pi reached `/ready` on :8000 in 110 ms and Tier 2 `/health` on :8001 in
8 ms. The backend container reached the Pi's MediaMTX on the Pi's tailnet
address.

## Before you start

- The user at that house has finished `docs/user-onboarding.md`. They are on the
  tailnet and have an app account.
- You have the hardware in `SETUP.md` §3.

Build and test the feeder at your house first. Then add their Wi-Fi and hand it
over. Problems are easier to fix on your own desk.

## 1. Flash the SD card

Use Raspberry Pi Imager with Raspberry Pi OS Lite, 64-bit. In the OS
customisation settings:

- Set a hostname that names the place, such as `peck-lakehouse`. It becomes the
  Pi's tailnet name and the default feeder name. Two Pis with the same hostname
  get confusing names on the tailnet.
- Create a user, and add your SSH public key.
- Enter your own Wi-Fi for now.

## 2. Join the tailnet

On the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Open the printed URL and sign in with the owner's Tailscale account. The Pi then
belongs to you, so you can reach it from home for maintenance.

In the Tailscale admin console, open the Pi's menu and select **Disable key
expiry**. Without this step, Tailscale signs the Pi out after 180 days. The
feeder then goes offline at a house where nobody knows why.

Note both tailnet addresses:

```bash
tailscale ip -4   # on the Pi
tailscale ip -4   # on the gaming PC
```

## 3. Install the code

```bash
sudo apt update
sudo apt install -y git python3-venv python3-picamera2
git clone https://github.com/dnorris823/Peck_Deck.git ~/peck_deck
cd ~/peck_deck
python3 -m venv --system-site-packages .venv
.venv/bin/pip install tflite-runtime -r raspberry_pi_code/requirements.txt
.venv/bin/python scripts/fetch_models.py
rpicam-hello --list-cameras
```

`--system-site-packages` is required. picamera2 comes from apt, and a plain venv
cannot import it.

The last command must list the camera.

## 4. Write the Pi's `.env`

The file is `raspberry_pi_code/.env`. The Pi service and the provisioning
script both read that path and no other, so a `.env` at the repo root is ignored.

```bash
cp raspberry_pi_code/.env.example raspberry_pi_code/.env
mkdir -p ~/peck_deck_cache
```

Set these values, with the gaming PC's tailnet address from step 2:

```
BACKEND_URL=http://<pc-tailnet-ip>:8000
INFERENCE_SERVER_URL=http://<pc-tailnet-ip>:8001
CACHE_DIR=/home/<user>/peck_deck_cache
```

Leave `DEVICE_TOKEN` alone. Step 6 writes it. Leave `TIER_PREFERENCE` at `gpu`.

Check that the Pi reaches the gaming PC, with the backend and Tier 2 running:

```bash
curl -m 5 http://<pc-tailnet-ip>:8000/ready
curl -m 5 http://<pc-tailnet-ip>:8001/health
```

## 5. Register the feeder in the app

Sign in to the web app as the user at that house. Use a private browser window
if you are on your own device. Go to **Feeders → Register feeder**.

- **Name:** the Pi's hostname, exactly. Provisioning finds the feeder by this
  name.
- **City and State:** where the feeder is. The backend looks up the weather for
  each sighting from these. To change them later, open the feeder under
  **Feeders** and edit **Details**.

Ignore the token the dialog shows. Provisioning fetches it.

The feeder now belongs to that user. They get its alerts, and nobody else sees
it yet.

## 6. Provision the device token

The Pi fetches its own device token at every start. It signs in with the
credentials in a root-only file:

```bash
sudo install -d -m 700 /etc/peck_deck
sudo tee /etc/peck_deck/owner.env >/dev/null <<'EOF'
PECK_OWNER_EMAIL=their-email@example.com
PECK_OWNER_PASSWORD=their-password
DEVICE_NAME=peck-lakehouse
EOF
sudo chmod 600 /etc/peck_deck/owner.env
```

Use the account of the user at that house, not your owner account. The variable
names say "owner", but any account that owns the feeder works. The owner
account can create users and manage every feeder. It does not belong on a Pi in
someone else's house.

Run the script once by hand:

```bash
env $(sudo cat /etc/peck_deck/owner.env | xargs) .venv/bin/python scripts/provision_device.py
```

It must print `matched existing device 'peck-lakehouse' (id N)`. Note the id. If
it prints `registered new device`, the name did not match step 5. It made a
second feeder with no city. Fix `DEVICE_NAME`, then open the extra feeder under
**Feeders** and use **Remove feeder**.

If that user changes their password later, the feeder keeps working. The token
does not depend on the password. Provisioning fails without harm until you
update this file. The token only needs fetching again after a database wipe or a
token rotation.

## 7. Add yourself to the feeder

Owners see only the feeders they own or belong to, so the new feeder is not in
your app yet. The user at that house shares it with you:

1. In the window signed in as that user, go to **Feeders** and open the feeder.
2. Under **Who sees this feeder**, enter your email in **Share with** and select
   **Add**.

You now see the feeder. You also get its alerts if your alerts are on.

## 8. Live video

Install MediaMTX as in `SETUP.md` §11. Two values differ from a feeder on the
home LAN.

`/etc/peck_deck/mediamtx.env`:

```
MTX_AUTHINTERNALUSERS_1_USER=<LIVE_READ_USER from the backend .env>
MTX_AUTHINTERNALUSERS_1_PASS=<LIVE_READ_PASSWORD from the backend .env>
MTX_WEBRTCADDITIONALHOSTS=<pi-tailnet-ip>
```

- The backend has one read user for all feeders. Every feeder's MediaMTX must
  use the same name and password, or every offer fails with 502.
- Give only the tailnet address. The Pi's LAN address at the other house is not
  known in advance, and MediaMTX offers every interface's address anyway.

Leave `LIVE_URL` unset. The Pi works it out from its route to `BACKEND_URL`.
With a tailnet `BACKEND_URL`, that gives the Pi's tailnet address, which the
backend accepts.

## 9. Install the services

Copy both units from `SETUP.md` §9. Replace `User=pi` with your user, and
`/home/pi/peck_deck` with `/home/<user>/peck_deck`. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now peck-deck mediamtx
journalctl -u peck-deck -f
```

## 10. Test it

Run the desk test in `SETUP.md` §10. Hold a bird photo up to the camera. The
sighting must reach the app for the user at that house, and for you. Open
**Live** and check the video plays.

## 11. Add their Wi-Fi and hand it over

Add their network before the Pi leaves your house. The command works when the
network is out of range:

```bash
sudo nmcli connection add type wifi con-name their-wifi ssid "<their SSID>" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<their password>"
nmcli connection show
```

At their house, the Pi joins the network it can see. Plug it in, wait two
minutes, and check that **Feeders** shows it online.

Then mount it and set `CAMERA_ROI` to the feeder's region, as in `SETUP.md`
§10. You do this from home over SSH:

```bash
ssh <user>@peck-lakehouse
```

## What the feeder depends on

| If this is down | The feeder |
|---|---|
| The gaming PC, or the backend | Keeps capturing and queues sightings. It uploads them when the backend comes back. |
| Tier 2 only | Classifies on the Pi with Tier 1, and uploads as usual. |
| Their internet | Same as the gaming PC being down. |
| The web app | Keeps working. Nobody can open the app until it comes back. |

The backend restarts with the PC. The web app and Tier 2 do not
([The web app and Tier 2 don't start after a PC reboot](https://github.com/dnorris823/Peck_Deck/issues/157)).

## Maintenance

From home, over SSH:

```bash
cd ~/peck_deck && git pull && sudo systemctl restart peck-deck
journalctl -u peck-deck --since today
```

`SETUP.md` §6 covers token rotation and removing a feeder.
