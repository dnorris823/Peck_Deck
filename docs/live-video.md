# Live video

The web app shows a feeder's camera live over WebRTC. The backend relays only
the signaling: one SDP offer, one SDP answer, one hang-up. The video goes
directly from the Pi to the browser and never reaches the gaming PC.

A browser that cannot reach the Pi plays HLS instead, and then every byte goes
through the backend. See "The HLS fallback" below.

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
| MediaMTX | the Pi, ports 8889 and 8888 | Answers WHEP at `http://<pi>:8889/feeder/whep` and serves LL-HLS at `http://<pi>:8888/feeder/`. Reads need the read user's Basic auth. |
| Address | `POST /devices/me/heartbeat` | The Pi sends `live_url` every 60 seconds. `devices.live_url` stores it. |
| Relay | `backend/live/controller.py`, `backend/live/whep.py`, `backend/live/hls.py` | Checks the JWT and device access, then forwards the offer and the hang-up, or the HLS files. |
| Address check | `backend/live/address.py` | Decides which `live_url` a heartbeat may store. |
| Browser | `frontend/src/live.js` | Sends the offer after ICE gathering completes, reads `live_available` from `GET /devices/`, and falls back to HLS. |

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

## The HLS fallback

Chrome on a Pixel 11 Pro sends no packet to any address on the home LAN. Its
signaling works, because that goes through the backend, and then ICE times
out. HLS through the backend needs only the HTTPS path the web app already
uses, so it plays wherever the app loads, away from home too. It costs delay.

```
browser ── GET /devices/{id}/live/hls/index.m3u8 (user JWT) ──▶ backend
backend ── GET http://<live_url host>:8888/feeder/index.m3u8 (Basic auth) ──▶ MediaMTX
browser ◀── playlists, init segments, segments, parts, all relayed ──
```

`live.js` tries WebRTC first. If ICE has not connected 5 seconds after the
answer, or fails before it ever connects, the player ends the WHEP session and
plays HLS with `hls.js`. It remembers that per device in `sessionStorage`, so
the next open in the same browser session goes straight to HLS. `?live=hls`
forces HLS, for testing on a desktop. The readout says "Live · relayed", with
the delay from `hls.js` and the frame rate from the video element.

`GET /devices/{device_id}/live/hls/{name}` takes a user JWT. `hls.js` sends it
from `xhrSetup`.

| Status | When |
|---|---|
| 200 | The file, streamed. `Content-Type` comes from MediaMTX. Playlists get `Cache-Control: no-store`. |
| 302 | MediaMTX's cookie check. `Location` is relative, such as `index.m3u8?cookieCheck=1`. |
| 401 | No JWT, or a device token. |
| 404 | No such device, the user cannot see it, or `name` is not one file name ending `.m3u8` or `.mp4`. |
| 502 | MediaMTX refused, most often mismatched read credentials. |
| 503 | `{"detail": "feeder not streaming"}`, as for WHEP. Also an expired segment, which MediaMTX answers with 404. |

- **MediaMTX tracks each HLS reader with a cookie.** Its first answer to
  `index.m3u8` is a 302 to `index.m3u8?cookieCheck=1` with a `Set-Cookie`. The
  relay passes the 302 on and drops the cookie. A client that comes back
  without the cookie gets `?session=<id>` on every URI in the playlists, and the
  query string passes through unchanged. No playlist is rewritten.
- **A playlist request can wait.** LL-HLS holds `_HLS_msn` and `_HLS_part`
  requests until that part exists, and the first request waits for the encoder.
  The relay allows 30 seconds of silence from MediaMTX, and streams bodies
  without buffering them.
- **The access check is cached.** A player asks for a part about every 200 ms.
  A successful check is kept 30 seconds per user, role and device, so most
  requests open no database session. A feeder that stops streaming is still
  asked for up to 30 seconds, and MediaMTX answers 404, which the relay turns
  into 503.
- **The encoder outlives an HLS viewer by about 50 seconds.** MediaMTX closes
  the muxer 10 seconds after the last request (`hlsMuxerCloseAfter`), closes the
  reader's session 30 seconds after that, and `runOnDemandCloseAfter` adds 10.
  A WebRTC viewer costs only the last 10.
- `LIVE_HLS_PORT` in the backend `.env` sets the port, default 8888. The host
  always comes from the stored `live_url`.

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
- **WebRTC media needs a direct path from the browser to the Pi.** Signaling
  works from anywhere the web app works. A browser without that path falls back
  to HLS, 1 to 3 seconds behind.

## Tests

`backend/tests/test_live.py` runs the WHEP and HLS relays against a fake
MediaMTX on 127.0.0.1. Loopback is not an allowed address, so those tests add it to
`ALLOWED_NETWORKS` for their own duration. No test reaches a real Pi.
