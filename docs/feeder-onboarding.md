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

## 3. Register the feeder in the app

Sign in to the web app as the user at that house. Use a private browser window
if you are on your own device. Go to **Feeders → Register feeder**.

- **Name:** the Pi's hostname, exactly. The install script finds the feeder by
  this name.
- **City and State:** where the feeder is. The backend looks up the weather for
  each sighting from these. To change them later, open the feeder under
  **Feeders** and edit **Details**.

Ignore the token the dialog shows. The Pi fetches it.

The feeder now belongs to that user. They get its alerts, and nobody else sees
it yet.

## 4. Run the install script

Start the backend and Tier 2 on the gaming PC first. Then, on the Pi:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/dnorris823/Peck_Deck.git ~/peck_deck
~/peck_deck/scripts/install_pi.sh
```

It asks these questions first, then runs on its own for several minutes.

| Question | Answer |
|---|---|
| Gaming PC tailnet address | `tailscale ip -4` on the gaming PC. |
| Feeder name | The name from step 3. It defaults to the hostname. |
| App email and password | The account of the user at that house. |
| Live video user and password | `LIVE_READ_USER` and `LIVE_READ_PASSWORD` in the backend `.env`. |
| Home Wi-Fi | The network at their house. Enter skips it. |
| Rescue phone hotspot | The hotspot name and password of a phone at their house. Enter skips it. |

Use the account of the user at that house, not your owner account. The owner
account can create users and manage every feeder. It does not belong on a Pi in
someone else's house.

The script then:

1. Installs the packages, the venv and the models, and checks the camera.
2. Writes `raspberry_pi_code/.env` with the gaming PC's tailnet address. The
   service reads that file and no other.
3. Writes the root-only `/etc/peck_deck/owner.env` and
   `/etc/peck_deck/mediamtx.env`. The MediaMTX file gets the Pi's tailnet
   address and the backend's one read user. Every feeder uses that same user,
   or every live offer fails with 502.
4. Installs MediaMTX v1.21.3 after it checks the checksum.
5. Writes the `peck-deck` and `mediamtx` units for your user and clone path.
6. Saves the two Wi-Fi networks. It never switches to them. The Pi stays on
   the network it uses now.
7. Checks that the backend and Tier 2 answer.
8. Fetches the device token, and starts both services.

It must print `matched existing device 'peck-lakehouse' (id N)`. If it warns
that it registered a new feeder, the name did not match step 3. Open the extra
feeder under **Feeders**, and use **Remove feeder**. Then run the script again
with the right name.

The script is safe to run again. Enter keeps every saved answer, and it keeps
`DEVICE_TOKEN`. Run it with `--dry-run` to see what it would change. Run it again
after a fix, such as a wrong password or a backend that was off.

Leave `LIVE_URL` and `TIER_PREFERENCE` alone. The Pi works out its live address
from its route to the gaming PC, which gives its tailnet address.

If that user changes their password later, the feeder keeps working. The token
does not depend on the password. Fetching it fails without harm until you run
the script again with the new password. The token only needs fetching again
after a database wipe or a token rotation.

`SETUP.md` has every step by hand, if the script fails partway.

## 5. Add yourself to the feeder

Owners see only the feeders they own or belong to, so the new feeder is not in
your app yet. The user at that house shares it with you:

1. In the window signed in as that user, go to **Feeders** and open the feeder.
2. Under **Who sees this feeder**, enter your email in **Share with** and select
   **Add**.

You now see the feeder. You also get its alerts if your alerts are on.

## 6. Test it

Run the desk test in `SETUP.md` §10. Hold a bird photo up to the camera. The
sighting must reach the app for the user at that house, and for you. Open
**Live** and check the video plays.

## 7. Hand it over

Fill in the blanks on `docs/feeder-handover.md`, print it, and give it to the
user at that house. It covers mounting, aiming with the Live tab, the feeder
card, and what to do when their Wi-Fi changes.

At their house, the Pi joins their saved network by itself. Plug it in, wait two
minutes, and check that **Feeders** shows it online.

Once it is mounted, set `CAMERA_ROI` to the feeder's region, as in `SETUP.md`
§10. You do this from home over SSH:

```bash
ssh <user>@peck-lakehouse
```

## When their Wi-Fi changes

A new router with the same Wi-Fi name and password needs nothing. Any other
change leaves the Pi offline, and nobody can SSH to an offline Pi. The rescue
hotspot fixes that:

1. They turn on the phone hotspot saved in step 4, near the feeder.
2. The Pi joins it, and comes back on the tailnet.
3. You SSH in and run `~/peck_deck/scripts/install_pi.sh --wifi`. Enter the new
   home network. Press Enter at the hotspot questions to keep it.
4. They turn the hotspot off. The Pi joins the new network within a few minutes.

The home network has priority 0 and the hotspot -10, so the Pi prefers the home
network when both are in range. It never leaves a working network for the
hotspot.

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
