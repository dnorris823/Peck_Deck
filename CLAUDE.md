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
├── backend/                   # Python REST API (Litestar or FastAPI)
├── frontend/                  # React web app
├── inference_server/          # GPU inference server (RTX 5080, gaming PC)
└── requirements.txt
```

## Tech Stack
| Layer | Technology |
|---|---|
| Pi runtime | Python 3.11+, asyncio |
| Pi classification (Tier 1) | TFLite runtime + INatVision model |
| Backend API | Python — **Litestar** framework (not FastAPI) |
| Database | SQLite, async via aiosqlite + SQLAlchemy |
| Frontend | React |
| GPU inference server | Python + PyTorch, RTX 5080 |
| Notifications | SMTP/SendGrid (email), Twilio (SMS) |
| Cloud classification | Claude API (Anthropic) multimodal |
| Auth | JWT |

**Important:** The backend uses **Litestar**, not FastAPI. Decorators, routing, and DI patterns differ — always follow Litestar idioms.

## Classification Tiers (priority order)
1. **Tier 1 — Local TFLite** — runs on Pi, no network needed
2. **Tier 2 — LAN GPU server** — Pi sends image to gaming PC inference server
3. **Tier 3 — Claude API** — cloud fallback, highest accuracy, requires API key

The Pi falls back from Tier 1 → 2 → 3 based on availability and confidence thresholds.

## Key Conventions
- **Async everywhere** — all DB and network I/O should be async.
- **Never store plain-text passwords** — always bcrypt before writing to DB.
- **Media files on disk** — DB stores relative paths only; files not served without auth.
- **Pi code is self-contained** — `raspberry_pi_code/` must run independently of the backend (it calls the API over HTTP).
- **Notifications are fire-and-forget** — never block the capture/upload pipeline waiting for email/SMS to send.
- **Secrets in env vars** — API keys (Claude, SendGrid, Twilio) go in `.env` files, never committed.

## Running Locally
```powershell
# Start the backend API (from project root)
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Start the GPU inference server (from project root)
python inference_server/main.py

# Start the React frontend (from frontend/)
npm run dev
```

## What's Not Built Yet (as of May 2026)
- React frontend (placeholder only)
- Raspberry Pi service pipeline
- GPU inference server
- Notification service
- Wikipedia lookup integration
- Claude API Tier 3 integration
- Offline queuing / retry logic on Pi
