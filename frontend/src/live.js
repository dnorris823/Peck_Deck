// Live video — the browser half of WHEP, against POST /devices/{id}/live/whep,
// with HLS through the backend as the fallback.
//
// The backend relays signaling only. The video goes from the Pi to the browser
// over WebRTC, so a session here keeps the Pi's software encoder running. That
// is why the stream stops whenever nobody can see it: the page hidden, the tab
// left, or the page unloading.
//
// No trickle ICE. The offer goes out once gathering completes, or after
// ICE_GATHER_MS, with whatever candidates exist by then.
//
// Some browsers cannot reach the Pi at all, even with signaling working. Chrome
// on a Pixel sends no packet to a LAN address. When ICE has not connected
// ICE_CONNECT_MS after the answer, the player switches to HLS from
// GET /devices/{id}/live/hls/index.m3u8. Every byte then comes through the
// backend, so it plays wherever the web app loads, 1 to 3 seconds behind.
import { apiDelete, apiPostSdp, getToken } from "./api.js";

export const ICE_GATHER_MS = 2000;
export const ICE_CONNECT_MS = 5000;
// sessionStorage, per device. Set when WebRTC fails to connect, so the next
// open of the Live tab in this browser session goes straight to HLS.
export const HLS_KEY_PREFIX = "peckdeck_live_hls_";
export const BASE_RETRY_MS = 1000;
export const MAX_RETRY_MS = 30000;
// Failed attempts in a row, never once live, before the screen says that live
// video needs the home network or Tailscale. Retries carry on regardless.
export const UNREACHABLE_AFTER = 3;
const STATS_MS = 1000;

/** The retry delay after `attempt` failures in a row: 1 s, 2 s, 4 s, up to 30 s. */
export function retryDelay(attempt) {
  return Math.min(BASE_RETRY_MS * 2 ** attempt, MAX_RETRY_MS);
}

/**
 * Frame rate and delay from one getStats() report, or nulls when the report has
 * no video yet. The delay is the jitter buffer plus half the round trip, in ms.
 * `prev` is the last inbound sample, for browsers without framesPerSecond.
 */
export function readStats(report, prev = null) {
  let inbound = null;
  let rtt = null;
  report.forEach((r) => {
    if (r.type === "inbound-rtp" && (r.kind === "video" || r.mediaType === "video")) inbound = r;
    if (r.type === "candidate-pair" && r.nominated && r.currentRoundTripTime != null) {
      rtt = r.currentRoundTripTime;
    }
  });
  if (!inbound) return { fps: null, delayMs: null, sample: null };

  let fps = inbound.framesPerSecond ?? null;
  if (fps == null && prev && inbound.framesDecoded != null && inbound.timestamp > prev.timestamp) {
    fps = ((inbound.framesDecoded - prev.framesDecoded) * 1000) / (inbound.timestamp - prev.timestamp);
  }
  let delayMs = null;
  if (inbound.jitterBufferEmittedCount > 0) {
    delayMs = (inbound.jitterBufferDelay / inbound.jitterBufferEmittedCount) * 1000;
    if (rtt != null) delayMs += (rtt * 1000) / 2;
  }
  return {
    fps: fps == null ? null : Math.round(fps),
    delayMs: delayMs == null ? null : Math.round(delayMs),
    sample: { timestamp: inbound.timestamp, framesDecoded: inbound.framesDecoded },
  };
}

// Resolves once ICE gathering completes, or after `ms`, whichever comes first.
function gathered(pc, ms) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    };
    const check = () => { if (pc.iceGatheringState === "complete") done(); };
    const timer = setTimeout(done, ms);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

/** Whether this player starts on HLS: `?live=hls`, or an earlier fallback. */
export function startsOnHls(deviceId, win = window) {
  if (new URLSearchParams(win.location?.search || "").get("live") === "hls") return true;
  try {
    return win.sessionStorage?.getItem(HLS_KEY_PREFIX + deviceId) === "1";
  } catch {
    return false;
  }
}

function rememberHls(deviceId, win) {
  try {
    win.sessionStorage?.setItem(HLS_KEY_PREFIX + deviceId, "1");
  } catch {
    /* storage off: the fallback still happens, just again next time */
  }
}

// Only a browser that needs the fallback loads hls.js. The light build has
// LL-HLS and leaves out DRM, subtitles and alternate audio, at 2/3 the size.
const loadHls = () => import("hls.js/light").then(m => m.default);

// The session URL as a path under the API, whether the server sent a path or a
// full URL.
function sessionPath(location) {
  if (!location) return null;
  return new URL(location, "http://peckdeck.invalid").pathname;
}

/**
 * Play feeder `deviceId` into `video` until `stop()` is called.
 *
 * `onStatus` receives `{ phase, fps, delayMs, unreachable, path }`. `path` is
 * "webrtc" or "hls", the way the video reaches this browser. `phase` is one of
 * "connecting", "live", "reconnecting", "paused", "offline" (the feeder cannot
 * stream, a 503) or "error" (no access, or the session ended). An "offline"
 * feeder is asked again every MAX_RETRY_MS.
 *
 * Returns `stop()`. Callers must call it, or the Pi keeps encoding.
 */
export function openLiveStream({ deviceId, video, onStatus, doc = document, win = window }) {
  let useHls = startsOnHls(deviceId, win);
  let status = {
    phase: "connecting", fps: null, delayMs: null, unreachable: false, path: useHls ? "hls" : "webrtc",
  };
  let stopped = false;
  // Bumped by every teardown, so an answer that lands after it is dropped.
  let generation = 0;
  let pc = null;
  let hls = null;
  let session = null;
  let retryTimer = null;
  let statsTimer = null;
  let iceTimer = null;
  let attempt = 0;
  let wasLive = false;

  function emit(patch) {
    status = { ...status, ...patch };
    onStatus?.(status);
  }

  // keepalive always, because a hide can be the first step of an unload, and
  // the DELETE has to finish after the page is gone.
  function endSession() {
    const path = session;
    session = null;
    if (path) apiDelete(path, { keepalive: true }).catch(() => {});
  }

  function teardown() {
    generation += 1;
    clearTimeout(retryTimer);
    clearTimeout(iceTimer);
    clearInterval(statsTimer);
    retryTimer = null;
    iceTimer = null;
    statsTimer = null;
    if (pc) {
      pc.oniceconnectionstatechange = null;
      pc.ontrack = null;
      pc.close();
      pc = null;
    }
    endSession();
    if (hls) {
      // Stops loading and detaches the video, so MediaMTX sees the reader leave.
      hls.destroy();
      hls = null;
    }
    if (video) video.srcObject = null;
  }

  // WebRTC signaled but never connected. Play the same feeder over HLS, now
  // and on every later open in this browser session.
  function fallBackToHls() {
    teardown();
    useHls = true;
    rememberHls(deviceId, win);
    emit({ path: "hls" });
    connect();
  }

  // An HLS failure, by the status the backend gave, handled the same as WHEP.
  function hlsFailed(code) {
    if (code === 401 || code === 403 || code === 404) {
      teardown();
      emit({ phase: "error", fps: null, delayMs: null });
    } else if (code === 503) {
      scheduleRetry("offline");
    } else {
      scheduleRetry("reconnecting");
    }
  }

  function scheduleRetry(phase) {
    teardown();
    const delay = phase === "offline" ? MAX_RETRY_MS : retryDelay(attempt);
    attempt += 1;
    emit({
      phase,
      fps: null,
      delayMs: null,
      unreachable: phase === "reconnecting" && !wasLive && attempt >= UNREACHABLE_AFTER,
    });
    retryTimer = setTimeout(connect, delay);
  }

  function connect() {
    if (stopped || doc.visibilityState === "hidden") return;
    teardown();
    // An offline feeder stays "offline" while it is asked again, so the screen
    // does not flash "Reconnecting" every 30 seconds.
    const phase = status.phase === "offline" ? "offline" : attempt === 0 ? "connecting" : "reconnecting";
    emit({ phase, fps: null, delayMs: null });
    if (useHls) connectHls();
    else connectWebRtc();
  }

  function goLive(startStatsFor) {
    attempt = 0;
    wasLive = true;
    emit({ phase: "live", unreachable: false });
    startStatsFor();
  }

  async function connectHls() {
    const mine = generation;
    let Hls;
    try {
      Hls = await loadHls();
    } catch {
      if (mine === generation && !stopped) scheduleRetry("reconnecting");
      return;
    }
    if (mine !== generation || stopped) return;
    if (!Hls.isSupported()) {
      // No Media Source Extensions, so nothing here can play the relay.
      emit({ phase: "error", fps: null, delayMs: null });
      return;
    }
    const player = new Hls({
      lowLatencyMode: true,
      // Every route needs the JWT, and only a header can carry it.
      xhrSetup: (xhr) => {
        const token = getToken();
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      },
    });
    hls = player;
    let playing = false;
    player.on(Hls.Events.FRAG_BUFFERED, () => {
      if (player !== hls || playing) return;
      playing = true;
      goLive(() => startHlsStats(player));
    });
    player.on(Hls.Events.ERROR, (_event, data) => {
      if (player !== hls || !data?.fatal) return;
      hlsFailed(data.response?.code);
    });
    player.on(Hls.Events.MANIFEST_PARSED, () => {
      video?.play?.()?.catch?.(() => {});
    });
    player.loadSource(`/api/devices/${deviceId}/live/hls/index.m3u8`);
    if (video) player.attachMedia(video);
  }

  async function connectWebRtc() {
    const mine = generation;
    pc = new RTCPeerConnection();
    const conn = pc;
    conn.addTransceiver("video", { direction: "recvonly" });
    conn.ontrack = (e) => {
      if (video) video.srcObject = e.streams?.[0] || new MediaStream([e.track]);
    };
    let connected = false;
    conn.oniceconnectionstatechange = () => {
      const state = conn.iceConnectionState;
      if (state === "connected" || state === "completed") {
        connected = true;
        clearTimeout(iceTimer);
        goLive(() => startStats(conn));
      } else if (state === "disconnected" || state === "failed") {
        // Never connected means this browser cannot reach the Pi. A drop after
        // connecting is the network, and WebRTC tries again.
        if (connected) scheduleRetry("reconnecting");
        else fallBackToHls();
      }
    };

    try {
      await conn.setLocalDescription(await conn.createOffer());
      await gathered(conn, ICE_GATHER_MS);
      if (mine !== generation) return;
      const { answer, location } = await apiPostSdp(
        `/devices/${deviceId}/live/whep`, conn.localDescription.sdp,
      );
      if (mine !== generation) {
        // Torn down while the POST was out. End the session it just opened.
        const path = sessionPath(location);
        if (path) apiDelete(path, { keepalive: true }).catch(() => {});
        return;
      }
      session = sessionPath(location);
      await conn.setRemoteDescription({ type: "answer", sdp: answer });
      if (mine !== generation || connected) return;
      iceTimer = setTimeout(() => {
        if (mine === generation && !connected) fallBackToHls();
      }, ICE_CONNECT_MS);
    } catch (err) {
      if (mine !== generation || stopped) return;
      if (err?.isAuthError || err?.status === 404 || err?.status === 403) {
        teardown();
        emit({ phase: "error", fps: null, delayMs: null });
      } else if (err?.status === 503) {
        scheduleRetry("offline");
      } else {
        scheduleRetry("reconnecting");
      }
    }
  }

  function startStats(conn) {
    clearInterval(statsTimer);
    let prev = null;
    statsTimer = setInterval(async () => {
      try {
        const { fps, delayMs, sample } = readStats(await conn.getStats(), prev);
        if (conn !== pc) return;
        prev = sample;
        emit({ fps, delayMs });
      } catch {
        /* a closed connection has no stats; the next state change says why */
      }
    }, STATS_MS);
  }

  // The delay is how far behind the live edge hls.js plays. The frame rate
  // comes from the frames the video element has shown.
  function startHlsStats(player) {
    clearInterval(statsTimer);
    let prev = null;
    statsTimer = setInterval(() => {
      if (player !== hls) return;
      const latency = player.latency;
      const delayMs = Number.isFinite(latency) && latency > 0 ? Math.round(latency * 1000) : null;
      const frames = video?.getVideoPlaybackQuality?.()?.totalVideoFrames;
      const now = Date.now();
      let fps = null;
      if (frames != null && prev && now > prev.at) {
        fps = Math.round(((frames - prev.frames) * 1000) / (now - prev.at));
      }
      if (frames != null) prev = { frames, at: now };
      emit({ fps, delayMs });
    }, STATS_MS);
  }

  function pause() {
    teardown();
    attempt = 0;
    emit({ phase: "paused", fps: null, delayMs: null });
  }

  function onVisibility() {
    if (doc.visibilityState === "hidden") pause();
    else if (!pc && !hls && !retryTimer && status.phase !== "error") connect();
  }
  // pagehide covers a close or a navigation away. pageshow brings a page back
  // from the back-forward cache.
  const onPageHide = () => pause();
  const onPageShow = (e) => { if (e.persisted) onVisibility(); };

  doc.addEventListener("visibilitychange", onVisibility);
  win.addEventListener("pagehide", onPageHide);
  win.addEventListener("pageshow", onPageShow);

  if (doc.visibilityState === "hidden") emit({ phase: "paused" });
  else connect();

  return function stop() {
    stopped = true;
    doc.removeEventListener("visibilitychange", onVisibility);
    win.removeEventListener("pagehide", onPageHide);
    win.removeEventListener("pageshow", onPageShow);
    teardown();
  };
}
