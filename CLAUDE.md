# Peck Deck — Claude Code Instructions

## What Is This Project
Peck Deck is a smart bird feeder system. A Raspberry Pi 5 with camera and trigger peripheral detects bird visits, captures images/video, classifies the species via one of three ML tiers, and notifies registered users. A React web app + Python backend running on a home gaming PC serves as the management hub.

See `PRD.md` for full product requirements.

## Repository Layout
```
Peck_Deck/
├── PRD.md                     # Product requirements — source of truth for scope
├── CLAUDE.md                  # This file
├── raspberry_pi_code/         # Pi-side capture + classification pipeline
├── machine_learning/          # Models, notebooks, taxonomy data
│   ├── INatVision_Small_2_fact256_8bit.tflite   # Tier 1 on-device model
│   ├── taxonomy.csv           # Maps model output indices → species names
│   └── yolo_test.ipynb        # YOLOv5n proof-of-concept notebook
├── backend/                   # Python REST API (Litestar)
│   └── notifications/         # Email (SendGrid) + SMS (Twilio) + Wikipedia lookup
├── inference_server/          # GPU inference server (RTX 5080, gaming PC)
├── frontend/                  # React web app (M5, not yet built)
└── requirements.txt
```

## Tech Stack
| Layer | Technology |
|---|---|
| Pi runtime | Python 3.11+, asyncio |
| Pi classification (Tier 1) | TFLite runtime + INatVision model |
| Backend API | Python — **Litestar** framework (not FastAPI) |
| Database | **PostgreSQL** (async via asyncpg + SQLAlchemy 2.0) |
| Media storage | Images stored as **bytea** in PostgreSQL (not on disk) |
| Deployment | **Docker + docker-compose** (two containers: `api` + `db`) |
| GPU inference server | Python + **FastAPI** + PyTorch/timm, RTX 5080 |
| Notifications | SendGrid (email), Twilio (SMS) — fire-and-forget |
| Cloud classification | Claude API (Anthropic) multimodal — M6 |
| Auth | JWT (users) + device token (Pi devices) |

**Important:** The backend uses **Litestar**, not FastAPI. The inference server uses FastAPI (separate service). Don't mix them up.

## Classification Tiers (priority order)
1. **Tier 1 — Local TFLite** — runs on Pi, no network needed
2. **Tier 2 — LAN GPU server** — Pi sends image to `inference_server/` at `POST /classify`
3. **Tier 3 — Claude API** — Pi sends image to `backend POST /classify`; backend relays to Claude API (M6)

The Pi falls back from Tier 1 → 2 → 3 based on availability and confidence thresholds.

## Key Conventions
- **Async everywhere** — all DB and network I/O should be async.
- **Never store plain-text passwords** — always bcrypt before writing to DB.
- **Images in DB as bytea** — `image_data` column on Sightings; served via `GET /sightings/{id}/image` (auth required).
- **Pi code is self-contained** — `raspberry_pi_code/` must run independently of the backend (it calls the API over HTTP).
- **Pi sighting upload is a single multipart POST** — Pi sends image bytes + metadata together to `POST /sightings`.
- **Notifications are fire-and-forget** — `asyncio.create_task()` in the sighting controller; notification service opens its own DB session.
- **Secrets in env vars** — API keys (Claude, SendGrid, Twilio) go in `.env` files, never committed.
- **Run via Docker** — `docker compose up` from project root starts both `api` and `db` containers.
- **Inference server runs bare-metal** — it needs direct GPU access; no Docker for the inference server.

## Running Locally
```powershell
# Start backend + database (from project root)
docker compose up --build

# Start the GPU inference server (from inference_server/)
# Install deps first: pip install -r inference_server/requirements.txt
# Also: pip install torch --index-url https://download.pytorch.org/whl/cu124
python -m inference_server

# Start the React frontend (from frontend/) — M5, not built yet
npm run dev
```

## What's Not Built Yet (as of May 2026)
- React frontend — M5
- Claude API Tier 3 integration — backend `POST /classify` returns 501 until M6
