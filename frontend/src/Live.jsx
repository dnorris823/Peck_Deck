// Live — the feeder's camera over WebRTC, with the latest bird in the corner.
// The player itself is live.js. This screen picks the feeder, shows the state,
// and falls back to an offline panel when the feeder cannot stream.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { openLiveStream } from "./live.js";
import { fmtClock, isUnknown } from "./home.js";
import { fmtRelative } from "./data.js";
import "./live.css";

export const FEEDER_KEY = "peckdeck_live_feeder";
// How long the corner pill names a new visitor.
export const PILL_MS = 60000;

const PHASE = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  paused: "Paused",
  offline: "Offline",
  error: "Unavailable",
};

const FEEDER = {
  online: { cls: "on", label: "Online" },
  warn: { cls: "warn", label: "Weak signal" },
  offline: { cls: "off", label: "Offline" },
};

/** The remembered feeder if it still exists, else the first that can stream. */
export function pickFeeder(devices, stored = localStorage.getItem(FEEDER_KEY)) {
  const remembered = devices.find(d => String(d.id) === stored);
  return remembered || devices.find(d => d.liveAvailable) || devices[0] || null;
}

/** "Northern Cardinal 92%", or "Bird here" when no tier named it. */
export function pillText(s) {
  if (isUnknown(s.species)) return "Bird here";
  return `${s.species.common} ${Math.round(s.confidence * 100)}%`;
}

// The newest sighting from this feeder that arrived after the screen opened.
// Shown for PILL_MS. A visit the Pi's offline queue sent late is not news.
function useArrival(sightings, deviceId) {
  const newest = sightings.find(s => s.device.id === deviceId);
  const baseline = useRef(null);
  const [shownId, setShownId] = useState(null);

  useEffect(() => {
    baseline.current = newest?.id ?? 0;
    setShownId(null);
    // Only a feeder switch resets the baseline. A new visit must not.
  }, [deviceId]);

  useEffect(() => {
    if (!newest || newest.id <= baseline.current || newest.delayed) return;
    baseline.current = newest.id;
    setShownId(newest.id);
  }, [newest]);

  useEffect(() => {
    if (shownId == null) return undefined;
    const t = setTimeout(() => setShownId(null), PILL_MS);
    return () => clearTimeout(t);
  }, [shownId]);

  // Looked up each render, so a species correction shows in the pill.
  return shownId == null ? null : sightings.find(s => s.id === shownId) || null;
}

function useFullscreen(wrapRef, videoRef) {
  const [full, setFull] = useState(false);
  useEffect(() => {
    const onChange = () => setFull(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [wrapRef]);

  const toggle = useCallback(() => {
    const wrap = wrapRef.current;
    const video = videoRef.current;
    if (document.fullscreenElement) document.exitFullscreen?.();
    else if (wrap?.requestFullscreen) wrap.requestFullscreen().catch(() => {});
    // iOS Safari on a phone can only take the video element itself fullscreen.
    else video?.webkitEnterFullscreen?.();
  }, [wrapRef, videoRef]);

  return [full, toggle];
}

function Readout({ status }) {
  const parts = [PHASE[status.phase] || "Connecting"];
  if (status.phase === "live") {
    if (status.fps != null) parts.push(`${status.fps} fps`);
    if (status.delayMs != null) parts.push(`${status.delayMs} ms`);
  }
  return (
    <span className={`live-readout ${status.phase}`}>
      <span className="live-readout-dot" aria-hidden="true" />
      {parts.join(" · ")}
    </span>
  );
}

function StatusStrip({ device, fps }) {
  const st = FEEDER[device.status] || FEEDER.offline;
  const visits = device.todaySightings ?? 0;
  return (
    <div className="live-strip">
      <span className="live-strip-item">
        <span className={`dot ${st.cls}`} aria-hidden="true" />
        <b>{device.name}</b> {st.label}
      </span>
      <span className="live-strip-item">{visits} visit{visits === 1 ? "" : "s"} today</span>
      <span className="live-strip-item">{fps == null ? "—" : fps} fps</span>
    </div>
  );
}

function OfflinePanel({ device, onCheck, checking }) {
  const seen = device.lastSeenAt;
  return (
    <section className="live-offline" aria-labelledby="live-offline-title">
      <div className="live-offline-icon" aria-hidden="true"><Icon name="video" className="" /></div>
      <h2 id="live-offline-title" className="live-offline-title">{device.name} isn't streaming</h2>
      <p className="live-offline-seen">
        {seen
          ? <>Last heartbeat {fmtClock(seen)}, {fmtRelative(seen)}</>
          : "No heartbeat yet"}
      </p>
      <ul className="live-offline-list">
        <li>Check that the feeder has power.</li>
        <li>Check that it is on Wi-Fi. The Feeders tab shows its signal.</li>
        <li>On the Pi, check that <code>mediamtx.service</code> runs: <code>systemctl status mediamtx</code></li>
      </ul>
      <button className="btn primary sm" onClick={onCheck} disabled={checking}>Check again</button>
    </section>
  );
}

function FeederPicker({ devices, value, onChange }) {
  if (devices.length < 2) return null;
  return (
    <div className="live-head">
      <select className="toolbar-select live-select" aria-label="Feeder" value={value}
        onChange={e => onChange(e.target.value)}>
        {devices.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
    </div>
  );
}

export function LivePage({ go }) {
  const { data, reload, loading } = useData();
  const { DEVICES, SIGHTINGS } = data;
  const [chosen, setChosen] = useState(() => pickFeeder(DEVICES)?.id ?? null);
  const device = DEVICES.find(d => d.id === chosen) || pickFeeder(DEVICES);
  const deviceId = device?.id ?? null;
  const available = !!device?.liveAvailable;

  const wrapRef = useRef(null);
  const videoRef = useRef(null);
  const [status, setStatus] = useState({ phase: "connecting", fps: null, delayMs: null, unreachable: false });
  const [full, toggleFull] = useFullscreen(wrapRef, videoRef);
  const arrival = useArrival(SIGHTINGS, deviceId);

  useEffect(() => {
    if (deviceId == null || !available) return undefined;
    setStatus({ phase: "connecting", fps: null, delayMs: null, unreachable: false });
    return openLiveStream({ deviceId, video: videoRef.current, onStatus: setStatus });
  }, [deviceId, available]);

  const choose = (id) => {
    localStorage.setItem(FEEDER_KEY, id);
    setChosen(Number(id));
  };

  if (!device) {
    return (
      <Empty title="No feeders yet" hint="Register a feeder to watch it live."
        action={<button className="btn primary sm" onClick={() => go("feeders")}>Register a feeder</button>} />
    );
  }

  const offline = !available || status.phase === "offline";
  const waiting = status.phase === "connecting" || status.phase === "reconnecting";

  return (
    <div className="live">
      <FeederPicker devices={DEVICES} value={device.id} onChange={choose} />

      {offline && <OfflinePanel device={device} onCheck={reload} checking={loading} />}

      {/* Mounted while offline too, so the player has a video element to fill
          the moment the feeder comes back. */}
      <section className={`live-stage ${full ? "full" : ""}`} ref={wrapRef} hidden={offline}
        aria-label={`Live video from ${device.name}`}>
        <video ref={videoRef} className="live-video" playsInline muted autoPlay />
        {arrival && (
          <span className="home-pill live-bird" role="status">
            <span className="home-pill-text">{pillText(arrival)}</span>
          </span>
        )}
        <Readout status={status} />
        {(waiting || status.phase === "paused" || status.phase === "error") && (
          <div className="live-wait" role="status">
            <div className="live-wait-text">
              {status.phase === "error"
                ? "You don't have access to this feeder's video."
                : status.phase === "paused" ? "Paused while the page is hidden." : `${PHASE[status.phase]}…`}
            </div>
            {status.unreachable && (
              <div className="live-wait-hint">
                Live video needs the home network or Tailscale. Check that this device is on one of them.
              </div>
            )}
          </div>
        )}
        <button type="button" className="live-full-btn" onClick={toggleFull}
          aria-label={full ? "Exit full screen" : "Full screen"} title={full ? "Exit full screen" : "Full screen"}>
          <Icon name={full ? "shrink" : "expand"} className="" />
        </button>
      </section>

      {!offline && <StatusStrip device={device} fps={status.fps} />}
    </div>
  );
}
