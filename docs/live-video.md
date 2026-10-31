# Live video

The web app shows a feeder's camera live over WebRTC. The backend relays only
the signaling: one SDP offer, one SDP answer, one hang-up. The video goes
directly from the Pi to the browser and never reaches the gaming PC.

## The flow

```
browser ── POST /devices/{id}/live/whep (SDP offer, user JWT) ──▶ backend
backend ── POST <live_url> (SDP offer, Basic auth) ─────────────▶ MediaMTX on the Pi
MediaMTX ── 201, SDP answer, Location: /feeder/whep/<session> ──▶ backend
backend ── 201, SDP answer, Location: /devices/{id}/live/whep/<session> ──▶ browser
browser ◀════════════ WebRTC media, direct ════════════▶ MediaMTX
browser ── DELETE /devices/{id}/live/whep/<session> ──▶ backend ── DELETE <live_url>/<session> ──▶ MediaMTX
```

| Piece | Where | Job |
|---|---|---|
| Camera | `raspberry_pi_code/`, `SETUP.md` | The Pi's one `PiCamera` feeds MediaMTX. MediaMTX starts the encoder on the first reader. |
| MediaMTX | the Pi, port 8889 | Answers WHEP at `http://<pi>:8889/feeder/whep`. Reads need the read user's Basic auth. |
| Address | `POST /devices/me/heartbeat` | The Pi sends `live_url` every 60 seconds. `devices.live_url` stores it. |
| Relay | `backend/live/controller.py`, `backend/live/whep.py` | Checks the JWT and device access, then forwards the offer and the hang-up. |
| Address check | `backend/live/address.py` | Decides which `live_url` a heartbeat may store. |
| Browser | `frontend/` | Sends the offer after ICE gathering completes, reads `live_available` from `GET /devices/`. |

## Why the backend relays the offer

The web app runs on HTTPS through Tailscale Serve (`docs/pwa-and-web-push.md`).
A browser on an HTTPS page cannot POST to `http://<pi>:8889`, because it blocks
mixed content. The relay keeps the offer same-origin. It also keeps the JWT and
the device access rules in force, and keeps the MediaMTX credentials off the
browser.

## The routes

`POST /devices/{device_id}/live/whep` takes the SDP offer with
`Content-Type: application/sdp` and a user JWT.

| Status | When |
|---|---|
| 201 | MediaMTX answered. The body is the SDP answer. `Location` is `/devices/{device_id}/live/whep/{session}`. |
| 400 | Empty offer, or MediaMTX rejected the SDP. |
| 401 | No JWT, or a device token. |
| 404 | No such device, or the user cannot see it. The two look the same. |
| 415 | The body is not `application/sdp`. |
| 502 | MediaMTX refused for another reason, most often mismatched read credentials. |
| 503 | `{"detail": "feeder not streaming"}`. No `live_url`, the device is offline, MediaMTX did not answer in 15 seconds, or it has no `feeder` stream. |

`DELETE /devices/{device_id}/live/whep/{session}` ends the session. It returns
204, or 503 if MediaMTX has no such session or does not answer. `PATCH` returns
405, because there is no trickle ICE.

## Things that bite

- **The relay keeps no session table.** The session id is the last path segment
  of MediaMTX's `Location`. On DELETE the backend rebuilds the session URL as
  `<live_url>/<session>`. A restart or a second API process loses nothing.
- **Neither route takes the `db` dependency.** The first offer can wait 15
  seconds for the encoder. `provide_db` would hold a pooled connection and a
  transaction for all of it. A short session does the lookup and closes first.
- **A device token chooses where the backend POSTs.** So the heartbeat accepts
  only an `http` or `https` URL whose host is an IPv4 literal in 10/8,
  172.16/12, 192.168/16, or 100.64/10 for Tailscale. Anything else gets 400. A
  hostname is refused, because it could resolve somewhere else later. The relay
  never follows a redirect, for the same reason.
- **A heartbeat without `live_url` clears it.** That is how the Pi says it
  stopped streaming. `live_available` is true only with a stored `live_url` and
  a device status other than `offline`. The URL itself never reaches the
  browser.
- **The credentials must match the Pi.** `LIVE_READ_USER` and
  `LIVE_READ_PASSWORD` in the backend `.env` must equal the read user in the
  Pi's MediaMTX config. A mismatch shows up as 502 on every offer.
- **The browser must reach the Pi directly for media.** Signaling works from
  anywhere the web app works. The media needs a network path from the browser
  to the Pi, on the LAN or over Tailscale.

## Tests

`backend/tests/test_live.py` runs the relay against a fake MediaMTX on
127.0.0.1. Loopback is not an allowed address, so those tests add it to
`ALLOWED_NETWORKS` for their own duration. No test reaches a real Pi.
