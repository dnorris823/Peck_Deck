# Windowsill test: setup and test plan

This plan covers the first real-bird test, tracked in
[Put the Pi at the window](https://github.com/dnorris823/Peck_Deck/issues/63).
The results feed
[Tune the detector and camera focus from real captures](https://github.com/dnorris823/Peck_Deck/issues/64).

The hardware is a bare Pi 5 and a Camera Module 3 Wide on a ribbon cable. The Pi
stays on the home Wi-Fi, so the agent on the gaming PC can reach it over SSH as
`peck-pi`.

## The site

The window looks onto a covered deck with a table and chairs.

- The left pane is fixed glass with no screen. The camera goes there.
- The right pane slides and has an insect screen. Do not shoot through it. The
  mesh blurs every frame.
- The seed goes on a plate on the table, on the edge nearest the window.
- The near row of chairs stands between the sill and the table. Their mesh
  backs hide the table top from a lens near the sill.
- A floor lamp stands to the right of the window. At night its light reflects off
  the glass.
- A plant leaf reaches into the lower left of the left pane.

The two largest risks are glare on the glass and a plate that is too far away.
The ribbon cable is a smaller risk.

## Distance matters most

The wide lens sees about 102 degrees across. A bird gets few pixels at a
distance. The table shows the width of a 14 cm finch in the 1920 px frame.

| Plate distance from the glass | Finch width in the frame |
|---|---|
| 0.5 m | about 220 px |
| 1.0 m | about 110 px |
| 1.5 m | about 75 px |

At 1 m, Tier 2 gets a usable crop. At 1.5 m the crop is weak. Measure the distance
from the glass to the near table edge. If it is more than about 1 m, put the plate
on a stool or a box closer to the glass.

## Setup

### 1. Clear the view

1. Move the two near chairs away from the window. Leave the table where it is.
2. Move the plant so no leaf crosses the left pane.
3. Clean the outside of the left pane where the lens will look through it.

### 2. Put out the seed

1. Use a shallow dish, or a paper plate held down with a stone. Wind lifts a
   loose paper plate.
2. Put it on the near table edge, in line with the middle of the left pane.
3. Put seed out a day before the test if you can. Birds can take days to find
   new food on an elevated, covered deck.

### 3. Mount the camera

1. Put the lens flat against the left pane, 30 to 40 cm above the sill. The lens
   looks straight out. At that height the plate is in the lower third of the
   frame, and the lens sees over the table edge.
2. Turn the board so the ribbon leaves from its bottom edge. The code has no flip
   or rotate setting, so an upside-down board gives upside-down sightings.
3. Hold the board with painter's tape or Blu Tack on its edges. Keep tape off the
   lens.
4. Put a dark hood behind the board. A black cardboard tube or a dark cloth taped
   to the glass will do. It stops room light and the lamp from reflecting into the
   lens.

### 4. Place the Pi and the ribbon

1. Set the Pi flat on the sill, below the camera. Keep it out of direct sun.
2. Tape the ribbon to the glass or the sill frame halfway between the board and
   the Pi. A tug then pulls the tape, not the connector on the Pi.
3. Bend the ribbon in a loose curve. Do not crease it.
4. Use the official Pi power supply. Run the cable so nobody catches it from the
   chair.

## Checks at the window

Do these in order. Use the Live tab on the phone. It shows the same camera
through the relay, so the service keeps running while you aim.

| Step | What to do | Pass |
|---|---|---|
| 1. Framing | Look at the Live tab. Move the board until the plate sits in the lower third, near the middle. | The plate is in frame and not cut off. |
| 2. Glare | Look with the lamp on, then off. | You cannot see the room, the lamp, or yourself in the image. |
| 3. Focus | Zoom in on the plate in the Live tab. | The seed looks sharp, not soft. Note it if it is soft, because the code sets no focus mode yet. |
| 4. No false fire | Wave a hand in front of the lens. Walk past the window. | No capture and no sighting. |
| 5. End to end | Open a bird photo full screen on a second phone or a tablet. Set it on the plate, facing the window. | One capture, one sighting in the app with a species, and one push on your phone. |
| 6. One visit | Leave the photo on the plate for a minute. | No second capture. |
| 7. New visit | Take the photo away for more than 15 s, then put it back. | A second capture. |
| 8. Tug | Nudge the Pi and the cable once. | The live view does not drop. |

Step 5 tests the real distance. If it does not fire, tell the agent before you
change anything. The detector region is not set yet, and that is the first fix.

## Checks the agent runs over Wi-Fi

### Before you go up

- The PC side runs: Docker (`api` and `db`), the Tier 2 server on port 8001, and
  the web app on port 4173. The Tier 2 server and the web app stop when the PC
  reboots.
- `BACKEND_URL` and `INFERENCE_SERVER_URL` in the Pi's `.env` match the PC's
  current LAN IP. The PC has no DHCP reservation, and its IP has changed before.
- `GET /ready` on the backend and `GET /health` on the Tier 2 server answer from
  the Pi.
- `peck-deck` and `mediamtx` are active. The service log shows
  `Camera trigger active`.

### While you are up there

| Check | Command on the Pi | Good result |
|---|---|---|
| Wi-Fi at the window | `iw dev wlan0 link` | Signal better than about -70 dBm |
| Heat | `vcgencmd measure_temp` | Under 70 °C |
| Power and throttling | `vcgencmd get_throttled` | `throttled=0x0` |
| Captures as they land | `journalctl -u peck-deck -f` | A detector score, a crop size, a Tier 2 species, and an upload with no queueing |

### Right after framing: set the detector region

The wide lens sees the whole deck and the houses behind it. The detector should
only look at the plate. `SETUP.md` section 10 explains `CAMERA_ROI`.

1. The agent stops `peck-deck` for a few seconds. The camera has one owner.
2. The agent takes one still with `rpicam-still` and copies it to the PC.
3. The agent finds the plate's box and writes it as fractions to `CAMERA_ROI` in
   the Pi's `.env`. Keep some margin around the plate for birds on its rim.
4. The agent starts `peck-deck` again. You repeat step 5 from the window checks.

## After a day

The agent reads the database and the images, then reports:

- Captures per hour, and how many came at night.
- The share of sightings stored as Unknown.
- The spread of Tier 2 confidence.
- The captures with no bird in them, and the captures with a blurry bird.

Those numbers set the values for
[Tune the detector and camera focus from real captures](https://github.com/dnorris823/Peck_Deck/issues/64):
the motion threshold, the detection threshold, the focus lock, and the shutter
limit.

## Expected trouble

- **The deck is shaded.** The roof makes frames darker than open sky. The
  shutter cannot be longer than one frame, 1/30 s at `LIVE_FPS=30`. A bird that
  moves fast may blur.
- **Cold glass.** If the inside of the pane fogs, the Live tab shows it as haze.
  Wipe the glass, then let the board settle.
- **The lamp at night.** If the hood does not stop its reflection, turn the lamp
  off or move it. The motion check can fire on a changing reflection.
- **Slow first visit.** No bird in the first hours is normal. The phone-photo test
  in step 5 proves the chain works while you wait.

## Do not merge during the test

The Pi and the backend both run from `main`. Hold the open PRs until the test has
a day of captures. One of them changes sign-in and needs a frontend rebuild.
