# PWA and web push (Phase 7)

Moved out of `CLAUDE.md`. The short warnings stay there; this is the detail.

The web app installs to a phone home screen, opens its shell without a network,
and can deliver a new-sighting alert as a browser notification.

```bash
# The service worker only registers in a production build, so this is how the
# PWA (install prompt, push) is exercised locally:
cd frontend && npm run build && npm run preview   # :4173, /api proxied

# Generate a VAPID keypair for push, then put it in .env (see .env.example)
python scripts/generate_vapid_keys.py

# Re-render the app icons after changing the brand mark (needs Pillow)
python scripts/generate_pwa_icons.py
```

## HTTPS is required

A service worker, and so web push, only works in a secure context. That means
HTTPS, or `localhost`. A phone that opens `http://192.168.x.x:4173` gets neither
the install prompt nor push. The app still works there, without alerts.

Nothing in this repo serves the web app over HTTPS. `docker compose` runs only
`api` and `db`, and the frontend runs from `npm run build && npm run preview`.
`frontend/vite.config.js` already allows `*.ts.net` hosts, so the intended route
is Tailscale. Put the gaming PC and the phone on one tailnet and publish the
preview port with Tailscale Serve. That gives a `https://<machine>.<tailnet>.ts.net`
URL with a real certificate. Open that URL on the phone.

On iOS, push also needs the app added to the Home Screen (iOS 16.4 or later).

Status: the test suite covers push with fake push services only. Send one real
alert to a real phone before relying on it.

| Piece | Where | Notes |
|---|---|---|
| Manifest + icons | `frontend/public/` | Icons are generated from the app's brand mark and committed. |
| Service worker | `frontend/public/sw.js` | Hand-written. Network-first app shell, cache-first hashed assets, the self-hosted font precached at install, and the push and notification-click handlers. It never caches an API response, a non-GET or a non-200. No `skipWaiting`, so a new worker takes over on the next visit. |
| Offline banner | `frontend/src/Offline.jsx` | Says "You're offline" and offers a retry. The page shows what it already loaded. |
| Push transport | `backend/notifications/push_sender.py` | RFC 8291 encryption + RFC 8292 VAPID on `cryptography` + `aiohttp`. Not `pywebpush`, which is synchronous and would need a thread per send. |
| Push routes | `GET /push/config`, `POST`/`DELETE /push/subscriptions` | Config reports `enabled:false` when no keys are set, and the web app hides the opt-in. |

Notes that will bite otherwise:

- **The VAPID public key is derived from the private key**, never read from
  `VAPID_PUBLIC_KEY` (which is only cross-checked). A mismatched pair fails only
  at delivery time, on every send.
- **Keep the keypair stable.** Browsers bake the public key into their
  subscription; rotating it silently invalidates every existing subscription.
- A 404/410 from a push service prunes the subscription; a 429/500 leaves it.
