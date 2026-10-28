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
4. The web app shows sightings live and sends push, email or SMS notifications.

Tier 3 sends hard cases through the backend to Claude. It stays in the code, off
by default. Tier 1 runs a small TFLite classifier on the Pi. It is no longer the
first stop.

## What is built

- Backend API (Litestar, PostgreSQL, Alembic migrations), with auth, devices,
  sightings, species, analytics and export.
- Web app (React), installable as a PWA, with live updates and web push.
- GPU inference server (FastAPI) for Tier 2.
- Pi code: capture, the tier chain, an offline queue and unattended device-token
  provisioning.
- A device simulator and a demo mode, so the app runs without a Pi.
- CI with backend, frontend and integration tests.

Measured accuracy on 300 field photos is in `machine_learning/MODELS.md`. No real
bird has been photographed at a real feeder yet.

## Next

The [Windowsill milestone](https://github.com/dnorris823/Peck_Deck/milestone/1) tracks these:

1. [Add a camera trigger](https://github.com/dnorris823/Peck_Deck/issues/61)
2. [Send every bird capture to Tier 2](https://github.com/dnorris823/Peck_Deck/issues/62)
3. [Put the Pi at the window](https://github.com/dnorris823/Peck_Deck/issues/63)
4. [Tune the detector and camera focus from real captures](https://github.com/dnorris823/Peck_Deck/issues/64)

## Where things are

| Topic | File |
|---|---|
| Running anything locally | `CONTRIBUTING.md` |
| Setting up the Pi | `SETUP.md` |
| Requirements | `PRD.md` |
| Models and measured accuracy | `machine_learning/MODELS.md` |
| Backups, migrations, health checks, tests | `docs/operations.md` |
| Live updates, demo mode, PWA and push | `docs/` |
| Camera focus and exposure notes | `docs/research/picamera2-focus-and-exposure.md` |
| Old plans, the outdoor build, agent config | `docs/archive/` |
