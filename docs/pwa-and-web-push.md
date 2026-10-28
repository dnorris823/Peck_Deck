# PWA and web push (Phase 7)

Moved out of `CLAUDE.md`. The short warnings stay there; this is the detail.

The web app installs to a phone home screen, opens offline to cached content, and
can deliver a new-sighting alert as a browser notification.

```bash
# The service worker only registers in a production build, so this is how the
# PWA (install prompt, offline reload, push) is exercised locally:
cd frontend && npm run build && npm run preview   # :4173, /api proxied

# Generate a VAPID keypair for push, then put it in .env (see .env.example)
python scripts/generate_vapid_keys.py

# Re-render the app icons after changing the brand mark (needs Pillow)
python scripts/generate_pwa_icons.py
```

| Piece | Where | Notes |
|---|---|---|
| Manifest + icons | `frontend/public/` | Icons are generated from the sidebar's own brand mark and committed. |
| Service worker | `frontend/public/sw.js` | Hand-written: network-first shell, cache-first hashed assets, network-first-with-fallback API reads. Never caches a non-GET or a non-200, so a 401 can't outlive the session. No `skipWaiting` — a new worker takes over on the next visit. |
| Offline reads | `frontend/src/offline.js` | Last raw API payloads in localStorage, re-mapped through `mapAll` on open. Cleared on sign-out. **Reads only** — no write queue. |
| Push transport | `backend/notifications/push_sender.py` | RFC 8291 encryption + RFC 8292 VAPID on `cryptography` + `aiohttp`. Not `pywebpush`, which is synchronous and would need a thread per send. |
| Push routes | `GET /push/config`, `POST`/`DELETE /push/subscriptions` | Config reports `enabled:false` when no keys are set, and the web app hides the opt-in. |

Notes that will bite otherwise:

- **The VAPID public key is derived from the private key**, never read from
  `VAPID_PUBLIC_KEY` (which is only cross-checked). A mismatched pair fails only
  at delivery time, on every send.
- **Keep the keypair stable.** Browsers bake the public key into their
  subscription; rotating it silently invalidates every existing subscription.
- **Push subscription writes are blocked in `DEMO_MODE`** and deliberately not on
  the allowlist — every demo visitor shares one account, so one subscription
  would push every later sighting to all the others' browsers.
- A 404/410 from a push service prunes the subscription; a 429/500 leaves it.
