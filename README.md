# Peck Deck

A smart bird feeder. A Raspberry Pi 5 with a camera watches the feeder. When a
bird shows up, the Pi takes a photo and sends it to the gaming PC. The gaming PC
names the species and stores the sighting. A React web app shows the sightings
and sends notifications.

## How it works

1. The Pi decides one thing: bird or no bird.
2. Every capture with a bird goes to the GPU inference server on the gaming PC
   (RTX 5080). This is Tier 2, and it is the main classifier.
3. The backend on the gaming PC stores the sighting and its image in PostgreSQL.
4. The web app shows sightings live and sends push or email notifications.

Tier 3 sends hard cases through the backend to Claude. It stays in the code, off
by default. Tier 1 runs a small TFLite classifier on the Pi. It is the fallback
when Tier 2 fails. `SETUP.md` §7 has the tier orders and how to turn Tier 3 on.

## What is built

- Backend API (Litestar, PostgreSQL, Alembic migrations), with auth, devices,
  sightings, species, analytics and export.
- Web app (React), installable as a PWA, with live updates and web push.
- GPU inference server (FastAPI) for Tier 2.
- Pi code: capture, the tier chain, an offline queue and unattended device-token
  provisioning.
- Animal visits. Tier 2 names a squirrel, raccoon or other feeder mammal, and the
  sighting records as an animal, outside every bird count.
- Feed alerts. An hourly check warns a feeder's owner when the feed is probably
  low or out, and a "Refilled" button on the feeder card resets it.
- CI with backend, frontend and integration tests.

Measured accuracy on 300 field photos is in `machine_learning/MODELS.md`.

On 2026-10-28 the whole chain ran once on the desk. The camera trigger saw a phone
photo of a house finch, Tier 2 on the 5080 named it House Finch at 63%, and the
sighting reached the app. No real bird has been photographed at a real feeder yet.

## Next

The [Windowsill milestone](https://github.com/dnorris823/Peck_Deck/milestone/1) tracks what is left:

1. [Classify the detector's crop, not the whole frame](https://github.com/dnorris823/Peck_Deck/issues/77)
2. [Put the Pi at the window](https://github.com/dnorris823/Peck_Deck/issues/63)
3. [Tune the detector and camera focus from real captures](https://github.com/dnorris823/Peck_Deck/issues/64)

The first is code. The other two need the Pi mounted and a feeder outside.
Smaller cleanups without a milestone are in the
[open issues](https://github.com/dnorris823/Peck_Deck/issues).

## Where things are

| Topic | File |
|---|---|
| Running anything locally | `CONTRIBUTING.md` |
| Setting up the Pi | `SETUP.md` |
| Adding a user | `docs/user-onboarding.md` |
| Adding a feeder at another house | `docs/feeder-onboarding.md` |
| Requirements | `PRD.md` |
| Models and measured accuracy | `machine_learning/MODELS.md` |
| Backups, migrations, health checks, tests | `docs/operations.md` |
| Live updates, PWA and push | `docs/` |
| Camera focus and exposure notes | `docs/research/picamera2-focus-and-exposure.md` |
| Old plans, the outdoor build, agent config | `docs/archive/` |
