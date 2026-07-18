# Peck Deck — Product Requirements Document

**Version:** 0.1 (Draft)
**Author:** Dominic Norris
**Date:** 2026-05-09

---

## 1. Overview

Peck Deck is a smart bird feeder system that automatically detects bird visits, captures images or short video clips, identifies the species using machine learning, and notifies registered users in real time. A companion web application running on the owner's home PC serves as the management hub for browsing sightings, managing users and devices, and configuring the system.

---

## 2. Goals

- Automatically detect and photograph birds visiting the feeder without user intervention.
- Accurately identify bird species using one of three classification tiers (local, LAN GPU, cloud).
- Notify registered users via email and/or SMS within seconds of a confirmed sighting.
- Provide a polished web app for browsing sighting history, managing users, and configuring the system.
- Run entirely from battery on the feeder hardware, with no external power required at the feeder.

---

## 3. Non-Goals (v1)

- Mobile native app (web app only for v1).
- Internet-accessible deployment (local network first; remote access is a future option).
- Multi-feeder fleet management.
- Real-time video streaming.
- Audio-based bird detection.

---

## 4. System Architecture

```
┌────────────────────────────────┐        WiFi        ┌──────────────────────────────────┐
│         Feeder Unit            │ ─────────────────▶ │       Home Gaming PC             │
│                                │                    │                                  │
│  Trigger Peripheral            │                    │  FastAPI / Litestar Backend       │
│  ↓                             │                    │  SQLite Database                 │
│  Raspberry Pi 5                │ ◀─ Classification ─│  GPU Inference Server (RTX 5080) │
│  ↓                             │                    │  React Web App                   │
│  Camera Module                 │                    │  Notification Service            │
│  ↓                             │                    │  (Email + SMS)                   │
│  Classification (local TFLite) │                    └──────────────────────────────────┘
│  ↓                             │                                  │
│  Upload sighting + image       │                                  ▼
└────────────────────────────────┘                    ┌─────────────────────┐
                                                      │  Registered Users   │
                                                      │  (Email / SMS)      │
                                                      └─────────────────────┘
```

### 4.1 Components

| Component | Platform | Responsibility |
|---|---|---|
| Trigger Peripheral | Feeder hardware | Signals Pi when a bird is present |
| Raspberry Pi 5 | Feeder hardware | Orchestrates capture, local inference, upload |
| Camera Module | Feeder hardware | Captures still images and short video clips |
| Battery Pack | Feeder hardware | Powers the entire feeder unit off-grid |
| Backend API | Gaming PC | REST API, business logic, auth |
| SQLite Database | Gaming PC | Persists users, devices, species, sightings |
| Inference Server | Gaming PC | GPU-accelerated classification (RTX 5080) |
| React Web App | Gaming PC | User-facing UI served from backend |
| Notification Service | Gaming PC | Sends email (SMTP/SendGrid) and SMS (Twilio) |

---

## 5. Feeder Hardware & Pi Pipeline

### 5.1 Trigger & Capture

- A dedicated trigger peripheral (e.g., PIR sensor, IR beam break) signals the Pi when a bird is present.
- On trigger, the Pi camera captures one high-resolution still image (primary classification input).
- **Video clips are deferred from the initial implementation.** A future release will add short clips (< 5 seconds). The Sightings data model includes a `video_path` field to avoid a schema migration later.
- A short debounce window (configurable, default 30s) prevents duplicate captures for the same visit.

### 5.2 Classification Tiers

The Pi attempts classification in order. If a tier fails or is disabled, it falls back to the next.

#### Tier 1 — Local (On-Device, Pi)
- Model: INatVision TFLite (quantized, runs on Pi CPU)
- No network required.
- Fastest response; lower accuracy ceiling.
- Used when offline or when configured as the preferred tier.

#### Tier 2 — LAN Inference Server (Gaming PC GPU)
- Model: Larger PyTorch model served over local WiFi from the gaming PC (RTX 5080).
- Higher accuracy than Tier 1; requires home network connectivity.
- The Pi sends the image to the server endpoint and receives a species prediction.
- **Fallback trigger:** If the inference server does not respond within ~5 minutes of the sighting, the Pi falls back to Tier 1. The cached image is synced and reclassified by the server once connection is restored.

#### Tier 3 — Cloud (Claude API)
- Model: Claude (Anthropic) multimodal API.
- Highest accuracy; requires internet access and a configured API key / account.
- Used as a fallback or for difficult identifications.
- Each classification tier returns: `common_name`, `scientific_name`, `confidence_score`.

### 5.3 Media Storage & Upload

**Local cache on Pi:** The Pi maintains a rolling cache of the last 25 captured images on local storage (SD card). Images beyond 25 are evicted oldest-first. This cache exists only as a short-term buffer — long-term storage is on the gaming PC.

**Normal flow (PC reachable):**
1. Pi streams the captured image directly to the backend API via multipart upload.
2. Backend saves the file to the PC's media directory and returns a storage path.
3. Pi posts a sighting record (species, device, timestamp, media path, confidence) to the API.
4. Backend triggers the notification service asynchronously.

**Offline / PC unreachable flow:**
- If the backend cannot be reached within a ~5-minute timeout, the Pi falls back to **Tier 1 local inference** and stores the sighting (image + classification) in the local cache.
- When connectivity is restored, the Pi automatically syncs all cached sightings to the backend: uploads the images, posts the sighting records, and clears them from local cache.
- Notifications are sent for synced sightings upon receipt by the backend (with a note that the sighting was delayed).

### 5.4 Power & Connectivity

- Entire feeder unit runs on battery (no mains power at feeder location).
- Network: WiFi only. The Pi connects to the home WiFi network.
- See Section 5.3 for the offline queuing and sync strategy.

---

## 6. Backend API

**Framework:** Python — Litestar (preferred) or FastAPI  
**Database:** SQLite (async, via aiosqlite + SQLAlchemy)  
**Auth:** JWT — login returns a token; all non-public endpoints require a valid token

### 6.1 Data Models

#### Users
| Field | Type | Notes |
|---|---|---|
| id | int | PK |
| name | str | Display name |
| email | str | Unique, used for login and notifications |
| password_hash | str | bcrypt |
| phone | str | Optional, E.164 format for SMS |
| notify_email | bool | Default true |
| notify_sms | bool | Default false |
| role | enum | `owner` \| `viewer` |

#### Devices
| Field | Type | Notes |
|---|---|---|
| id | int | PK |
| name | str | Friendly name (e.g., "Backyard Feeder") |
| city | str | |
| state | str | |
| owner_id | int | FK → Users |
| classification_tier | enum | `local` \| `gpu` \| `cloud` \| `auto` |
| feed_type | str | Optional (e.g., sunflower seeds) |

#### DeviceUsers (junction)
| Field | Type | Notes |
|---|---|---|
| device_id | int | FK → Devices |
| user_id | int | FK → Users |

#### Species
| Field | Type | Notes |
|---|---|---|
| id | int | PK |
| common_name | str | |
| genus | str | |
| species | str | |
| order | str | Taxonomic order |
| wiki_url | str | Auto-populated at first sighting (see Section 9.1) |

Species records are created on-demand — the table is empty at startup and a new row is inserted the first time a species is classified. Subsequent sightings of the same species reuse the existing record.

#### Sightings
| Field | Type | Notes |
|---|---|---|
| id | int | PK |
| species_id | int | FK → Species |
| device_id | int | FK → Devices |
| datetime | datetime | UTC timestamp |
| image_path | str | Relative path to stored image |
| video_path | str | Relative path to stored video (nullable) |
| classification_tier_used | str | Which tier produced the result |
| confidence_score | float | 0.0–1.0 |
| weather_conditions | str | Optional |

### 6.2 API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /login | Authenticate, return JWT |
| POST | /users | Register a new user |
| GET | /users/{id} | Get user profile |
| PUT | /users/{id} | Update user settings |
| DELETE | /users/{id} | Remove user |
| GET | /devices | List devices for authenticated user |
| POST | /devices | Register a new device |
| PUT | /devices/{id} | Update device settings |
| POST | /devices/{id}/users | Add a user to a device |
| DELETE | /devices/{id}/users/{uid} | Remove a user from a device |
| GET | /sightings | List sightings (filterable by device, species, date) |
| POST | /sightings | Create sighting (called by Pi) |
| GET | /sightings/{id} | Get single sighting + media |
| GET | /species | List known species |
| POST | /species | Add a species record |
| GET | /species/{id} | Get species detail |
| POST | /classify | Accept an image, return species prediction (Tier 2 GPU endpoint) |

---

## 7. Notification System

Triggered by the backend after a new sighting is saved. Notifications are sent to all users registered on the device that recorded the sighting.

### 7.1 Email Notification

Sender: Configured SMTP account or SendGrid API key.

**Email contains:**
- Subject: `Peck Deck: [Common Name] spotted at [Device Name]!`
- Captured image or video thumbnail (inline or attachment).
- Species common name and scientific name.
- Total number of times this species has been seen at this device.
- Link to the Wikipedia page for the species.
- Link to the sighting detail page in the web app.

### 7.2 SMS Notification

Sender: Twilio phone number.

**SMS contains (concise):**
- `🐦 Peck Deck: [Common Name] at [Device Name] — sighting #[N]. [Wikipedia URL]`
- Media URL to the captured image (MMS if supported).

### 7.3 Notification Rules
- Users can toggle email and SMS notifications independently in their profile settings.
- A minimum interval between notifications per device (configurable, default 60s) prevents spam during a long visit.
- Notification failures are logged but do not block the sighting from being saved.

---

## 8. Web Application

**Stack:** React frontend + Python backend (same process)  
**Access:** Local network only (v1); owner's gaming PC serves the app.

### 8.1 Pages

#### Dashboard
- Recent sightings feed (image, species, device, timestamp).
- Quick stats: total sightings today, total species seen, most frequent visitor.
- Live status indicator for each registered device (online/offline).

#### Sighting Gallery
- Browsable grid of all sightings with filtering by species, device, and date range.
- Clicking a sighting opens a detail view with the full image/video, species card, and sighting history for that species.

#### Species Library
- List of all species ever recorded by the user's devices.
- Each species card shows: photo, common name, scientific name, total sighting count, first seen date, link to Wikipedia.

#### Devices
- List of registered feeders.
- Per-device settings: name, location, classification tier preference, feed type.
- Add/remove users who receive notifications for this device.

#### User Management (Owner only)
- Invite new users by email.
- View and manage existing users' notification preferences and roles.

#### Settings
- Classification tier preference (global default).
- Email and SMS notification toggles.
- API key management (Claude API key for Tier 3, SendGrid key, Twilio credentials).
- Account details (name, email, phone, password change).

---

## 9. Classification Model Details

### Tier 1 — INatVision TFLite (On-Device)
- Quantized 8-bit model designed for edge inference.
- Trained on iNaturalist data; strong coverage of North American bird species.
- Input: 224×224 RGB image.
- Output: species probability distribution; top prediction + confidence returned.
- Taxonomy reference: `taxonomy.csv` maps model output indices to species names.

### Tier 2 — GPU Inference Server
- Python HTTP service running on gaming PC, exposed on LAN.
- Accepts multipart image upload, returns JSON prediction.
- Model TBD (candidates: larger iNaturalist model, fine-tuned EfficientNet, or YOLO-based detector + classifier pipeline).
- RTX 5080 allows for real-time inference even on large models.

### Tier 3 — Claude API (Cloud)
- Sends captured image to Claude multimodal API with a species-identification prompt.
- Prompt instructs Claude to return structured JSON: `{common_name, scientific_name, confidence}`.
- API key stored securely in backend settings; never exposed to the Pi.
- Pi sends image to backend, backend calls Claude API and returns result.

### 9.1 Wikipedia URL Lookup

When a new species is first seen, the backend automatically resolves the Wikipedia URL. It tries each method in order and stops at the first success:

1. **Wikipedia API** — `https://en.wikipedia.org/api/rest_v1/page/summary/{species_name}` returns a canonical URL and a short description. Preferred: fast, structured, reliable.
2. **Web search** — If the API returns no result, fall back to a web search query (`"{common_name} bird site:en.wikipedia.org"`) and extract the first Wikipedia link from results.
3. **Web scrape** — If neither above works, construct the standard Wikipedia URL pattern (`https://en.wikipedia.org/wiki/{Common_Name}`) and verify it returns a 200 response.

The resolved URL and a short description (from the API when available) are stored in the `Species` record. A failed lookup is logged but does not block the sighting from being saved — the field is left null and retried on the next sighting of the same species.

---

## 10. Security Considerations

- All API endpoints except `/login` require a valid JWT.
- Passwords stored as bcrypt hashes only.
- API keys (Claude, SendGrid, Twilio) stored in environment variables or a secrets file on the gaming PC, never committed to version control.
- Pi authenticates to the backend API using a device-specific token (not a user JWT).
- Media files stored in a local directory not directly served without auth.

---

## 11. Open Questions

1. **Trigger peripheral model** — What specific peripheral is being used? This affects debounce timing and Pi GPIO integration details.
2. **Feeder solar charging** — Is solar charging planned for the battery, or strict finite battery life between charges?

---

## 12. Milestones

| Milestone | Description |
|---|---|
| M1 — Hardware + Local Inference | Pi captures images on trigger, classifies with TFLite, logs to local file |
| M2 — Backend API + Database | Full CRUD API running on gaming PC, Pi posts sightings via API |
| M3 — GPU Inference Server | Tier 2 classification server running on gaming PC |
| M4 — Notification Service | Email + SMS notifications on new sightings |
| M5 — Web App | React frontend: dashboard, gallery, species library, settings |
| M6 — Cloud Classification | Claude API Tier 3 integration |
| M7 — Polish & Hardening | Error handling, offline queuing, battery optimization, UI polish |
