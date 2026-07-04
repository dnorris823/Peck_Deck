# Peck Deck — Frontend (Milestone 5)

React + Vite web app for the Peck Deck field station, ported from the
[Claude Design](https://claude.ai/design/p/019e1019-61f5-713c-9dcb-1bf977af0748)
prototype (`Peck Deck.html`).

## Requirements

- Node.js 20+ and npm

## Getting started

```bash
cd frontend
npm install
npm run dev      # dev server on http://localhost:5173
```

`npm run build` produces a static bundle in `dist/`; `npm run preview` serves it.

## Structure

| File | Responsibility |
|---|---|
| `src/main.jsx` | React entry point |
| `src/App.jsx` | Top-level routing, theming, live-alert toast |
| `src/Shell.jsx` | Sidebar nav, topbar, brand mark (`NAV`) |
| `src/Icon.jsx` | Inline SVG icon set |
| `src/BirdPlate.jsx` | Stylized field-guide bird silhouette plates |
| `src/Dashboard.jsx` | Dashboard: stats, recent feed, heatmap, top visitors |
| `src/Sightings.jsx` | Sightings gallery + sighting detail modal |
| `src/Species.jsx` | Species library + species detail modal |
| `src/Devices.jsx` | Devices list + per-station settings modal |
| `src/UsersSettings.jsx` | Users management + Settings pages |
| `src/api.js` | Fetch client: token storage, `login()`, `apiGet()` |
| `src/Login.jsx` | Sign-in gate (exchanges credentials for a JWT) |
| `src/DataContext.jsx` | Loads all datasets after login; `useData()` hook |
| `src/data.js` | Backend adapters (`loadAll()`) + date/time helpers |
| `src/styles.css` | Full design system (field-journal theme, day/dusk) |

## Backend wiring

The app is wired to the Litestar backend (no more mock fixtures).

- **Auth:** `App.jsx` shows `Login` until a JWT is stored. `api.js` keeps the
  token in `localStorage` and attaches it as a `Bearer` header on every request.
- **Data:** after login, `DataProvider` calls `loadAll()` (in `data.js`), which
  fetches `/species`, `/stats/species-counts`, `/devices`, `/users`,
  `/sightings`, `/stats/heatmap`, and `/stats/dashboard` in parallel and adapts
  the snake_case responses into the shapes the pages consume. Pages read them
  via `useData()`. A global loading/error gate means pages can assume data is
  present.
- **Proxy:** `vite.config.js` proxies `/api/*` → `http://localhost:8000` and
  strips the `/api` prefix, so `apiGet("/species")` hits the backend `GET
  /species`.

### Running against the backend

```bash
# 1. Start backend + Postgres (from project root)
docker compose up --build
# 2. Seed demo data (species w/ plates, 3 devices, ~7 days of sightings)
python -m backend.seed
# 3. Start the frontend
cd frontend && npm run dev
```

Demo login: **dom@peck.deck** / **peckdeck** (see `backend/seed.py`).

Captured photos are stored as bytea and served by `GET /sightings/{id}/image`
(auth required). The current design renders stylized SVG plates rather than the
real photos, so that endpoint isn't consumed yet — wiring it up would need a
blob fetch with the `Authorization` header (a plain `<img src>` can't send it).

## Notes

- The design's floating "Tweaks" panel was a Claude Design canvas tool and is
  intentionally not ported. Its appearance defaults (theme/accent/font) live in
  `APPEARANCE` in `App.jsx` and are applied on load.
- Fonts load from Google Fonts (see `index.html`).
