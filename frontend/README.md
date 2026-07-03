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
| `src/data.js` | **Mock fixtures** — replace with backend API calls |
| `src/styles.css` | Full design system (field-journal theme, day/dusk) |

## Wiring to the backend

`src/data.js` currently exports hard-coded fixtures. Replace these with `fetch`
calls to the Litestar backend (`GET /species`, `/devices`, `/users`,
`/sightings`). `vite.config.js` proxies `/api/*` → `http://localhost:8000` in
dev, so call e.g. `fetch("/api/sightings")`. Auth: attach the JWT from `POST
/login` as a `Bearer` header.

## Notes

- The design's floating "Tweaks" panel was a Claude Design canvas tool and is
  intentionally not ported. Its appearance defaults (theme/accent/font) live in
  `APPEARANCE` in `App.jsx` and are applied on load.
- Fonts load from Google Fonts (see `index.html`).
