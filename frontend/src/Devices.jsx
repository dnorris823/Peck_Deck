// Devices page — list of stations with full settings
import React, { useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, SelectInput, FormNote } from "./Modal.jsx";
import { createDevice } from "./data.js";

const TIER_OPTIONS = [
  ["", "Inherit my default"],
  ["auto", "Auto"],
  ["local", "Tier 1 — Local"],
  ["gpu", "Tier 2 — LAN GPU"],
  ["cloud", "Tier 3 — Cloud"],
];

function RegisterDeviceModal({ onClose, onDone }) {
  const [form, setForm] = useState({ name: "", city: "", state: "", feed_type: "", classification_tier: "" });
  const [token, setToken] = useState(null); // device token, shown once after create
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  async function submit() {
    if (!form.name) { setError("A station name is required."); return; }
    setBusy(true);
    setError(null);
    try {
      const body = { name: form.name, city: form.city || null, state: form.state || null, feed_type: form.feed_type || null };
      if (form.classification_tier) body.classification_tier = form.classification_tier;
      const device = await createDevice(body);
      setToken(device.token); // reveal once; the Pi needs it to authenticate
      await onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  if (token) {
    return (
      <Modal
        title="Station registered"
        subtitle="Copy this device token now — it's shown only once and is needed to provision the Pi."
        onClose={onClose}
        footer={<button className="btn primary" onClick={onClose}>Done</button>}
      >
        <div className="card" style={{ padding: "12px 16px", fontFamily: "var(--mono)", fontSize: 12, wordBreak: "break-all" }}>
          {token}
        </div>
        <button className="btn" onClick={() => navigator.clipboard?.writeText(token)}>Copy token</button>
      </Modal>
    );
  }

  return (
    <Modal
      title="Register a station"
      subtitle="Add a new feeder. You'll get a device token to provision the Pi."
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Registering…" : "Register"}</button>
      </>}
    >
      <TextInput label="Name" value={form.name} onChange={set("name")} />
      <TextInput label="City" value={form.city} onChange={set("city")} />
      <TextInput label="State" value={form.state} onChange={set("state")} />
      <TextInput label="Bait / feed type" help="Optional." value={form.feed_type} onChange={set("feed_type")} />
      <SelectInput label="Classifier tier" value={form.classification_tier} onChange={set("classification_tier")}
        options={TIER_OPTIONS} />
      <FormNote error={error} />
    </Modal>
  );
}

function StationFigure({ d }) {
  // Stylized "feeder station" diagram with battery, signal, sensor
  const pct = Math.round(d.battery * 100);
  const batColor = pct > 50 ? "var(--forest)" : pct > 20 ? "var(--yolk)" : "var(--cardinal)";
  return (
    <svg viewBox="0 0 220 160" style={{ width: "100%", height: "100%" }}>
      <defs>
        <linearGradient id={`sky-${d.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(107, 155, 184, 0.18)" />
          <stop offset="100%" stopColor="rgba(107, 155, 184, 0.04)" />
        </linearGradient>
      </defs>
      <rect width="220" height="160" fill={`url(#sky-${d.id})`} />
      {/* ground */}
      <line x1="0" y1="138" x2="220" y2="138" stroke="var(--hairline-strong)" strokeWidth="1" strokeDasharray="2 3" />

      {/* Tree branch */}
      <path d="M 30 138 Q 60 130 80 132 Q 100 134 120 128" stroke="var(--ink-soft)" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <path d="M 80 132 L 75 110" stroke="var(--ink-soft)" strokeWidth="1.5" fill="none" strokeLinecap="round" />

      {/* Feeder pole */}
      <line x1="155" y1="138" x2="155" y2="60" stroke="var(--ink-soft)" strokeWidth="1.5" />
      {/* Feeder body */}
      <g transform="translate(120, 40)">
        <path d="M 0 22 L 35 8 L 70 22 L 70 50 L 0 50 Z" fill="var(--paper-2)" stroke="var(--ink-soft)" strokeWidth="1.2" />
        <path d="M 0 22 L 35 8 L 70 22" fill="var(--ink-soft)" opacity="0.18" />
        <line x1="35" y1="8" x2="35" y2="50" stroke="var(--hairline-strong)" />
        <circle cx="20" cy="34" r="2" fill="var(--cardinal)" />
        <circle cx="50" cy="34" r="2" fill="var(--cardinal)" />
        {/* camera */}
        <rect x="30" y="-6" width="10" height="8" rx="1" fill="var(--ink)" />
        <circle cx="35" cy="-2" r="2" fill="var(--cardinal)" />
        {/* signal arcs */}
        <path d="M 47 -3 q 4 0 6 4" stroke={d.status === "online" ? "var(--forest)" : "var(--ink-mute)"} strokeWidth="1.2" fill="none" strokeLinecap="round" />
        <path d="M 51 -7 q 7 1 11 8" stroke={d.status === "online" ? "var(--forest)" : "var(--ink-mute)"} strokeWidth="1.2" fill="none" strokeLinecap="round" opacity={d.signal === "weak" ? 0.3 : 0.85} />
      </g>

      {/* Tiny bird perched */}
      <g transform="translate(82, 100)" fill="var(--ink)" stroke="var(--cardinal)" strokeWidth="0.5">
        <path d="M 0 8 C -2 4 0 0 4 -1 C 8 -2 13 -1 16 2 L 19 0 L 22 2 L 19 5 C 21 8 18 11 14 11 L 12 14 L 8 13 L 6 15 L 5 12 L 2 13 Z" />
      </g>

      {/* Battery and stats overlay */}
      <g transform="translate(12, 12)">
        <rect x="0" y="0" width="76" height="46" rx="3" fill="var(--paper)" stroke="var(--hairline-strong)" />
        <text x="8" y="14" fontFamily="'Geist Mono', monospace" fontSize="8" letterSpacing="1.5" fill="var(--ink-mute)">BATTERY</text>
        <text x="8" y="32" fontFamily="'Newsreader', serif" fontStyle="italic" fontSize="20" fill="var(--ink)">{pct}%</text>
        <rect x="8" y="36" width="60" height="4" rx="0.5" fill="var(--paper-2)" stroke="var(--hairline)" />
        <rect x="8" y="36" width={60 * d.battery} height="4" rx="0.5" fill={batColor} />
      </g>
    </svg>
  );
}

function DeviceListCard({ d, onClick }) {
  const dotCls = d.status === "online" ? "on" : d.status === "warn" ? "warn" : "off";
  const tierLabels = { local: "Local · TFLite", gpu: "LAN · RTX 5080", cloud: "Cloud · Claude", auto: "Auto" };
  return (
    <div className="card" style={{ overflow: "hidden", cursor: "pointer" }} onClick={() => onClick(d)}>
      <div style={{ aspectRatio: "1.6", borderBottom: "1px solid var(--hairline)" }}>
        <StationFigure d={d} />
      </div>
      <div className="card-pad">
        <div className="between" style={{ marginBottom: 10 }}>
          <div>
            <div className="device-name">{d.name}</div>
            <div className="device-loc">{d.city}, {d.state}</div>
          </div>
          <div className="device-status">
            <span className={`dot ${dotCls}`} />
            {d.status === "online" ? "Online" : d.status === "warn" ? "Low signal" : "Offline"}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, fontSize: 12, color: "var(--ink-soft)" }}>
          <div>
            <div className="label">Classifier</div>
            <div style={{ marginTop: 3, color: "var(--ink)" }}>{tierLabels[d.tier]}</div>
          </div>
          <div>
            <div className="label">Bait</div>
            <div style={{ marginTop: 3, color: "var(--ink)" }}>{d.feed}</div>
          </div>
        </div>
        <div className="device-stats">
          <div>
            <div className="device-stat-num tnum">{d.todaySightings}</div>
            <div className="device-stat-lbl">Today</div>
          </div>
          <div>
            <div className="device-stat-num tnum">{d.weekSightings}</div>
            <div className="device-stat-lbl">7 days</div>
          </div>
          <div>
            <div className="device-stat-num tnum">{d.allTime.toLocaleString()}</div>
            <div className="device-stat-lbl">All time</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function DeviceDetail({ d, onClose }) {
  const { USERS } = useData().data;
  const tierLabels = {
    local: { name: "Tier 1 — Local", desc: "On-device TFLite, no network needed" },
    gpu: { name: "Tier 2 — LAN GPU", desc: "Forwards to RTX 5080 inference server" },
    cloud: { name: "Tier 3 — Cloud", desc: "Hard cases sent to Claude" },
    auto: { name: "Auto", desc: "Local first, escalate when confidence < 70%" },
  };
  const [tier, setTier] = useState(d.tier);
  const allowedUsers = USERS.slice(0, 3);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}><Icon name="x" className="" /></button>
        <div style={{ padding: "28px 32px" }}>
          <div className="label" style={{ marginBottom: 8 }}>Station settings</div>
          <h2 className="display" style={{ fontSize: 38, lineHeight: 1, margin: 0 }}>{d.name}</h2>
          <div className="display-i" style={{ fontSize: 17, color: "var(--ink-soft)", marginTop: 4 }}>
            {d.city}, {d.state}
          </div>

          <div className="settings-section" style={{ marginTop: 24 }}>
            <div className="label" style={{ marginBottom: 12 }}>Classification preference</div>
            <div className="tier-stack">
              {Object.entries(tierLabels).map(([key, t], i) => (
                <div key={key} className={`tier-card ${tier === key ? "selected" : ""}`} onClick={() => setTier(key)}>
                  <div className="tier-num">{i + 1}</div>
                  <div>
                    <div className="tier-name">{t.name}</div>
                    <div className="tier-desc">{t.desc}</div>
                  </div>
                  <span className="tier-badge">{key.toUpperCase()}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="settings-section">
            <div className="between" style={{ marginBottom: 12 }}>
              <div className="label">Notification recipients</div>
              <button className="btn ghost sm"><Icon name="plus" className="" /> Invite</button>
            </div>
            <div className="card">
              {allowedUsers.map(u => (
                <div className="user-row" key={u.id}>
                  <div className="av-lg" style={{ background: u.avBg }}>{u.av}</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{u.name}</div>
                    <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>{u.email}</div>
                  </div>
                  <span className={`role-badge role-${u.role}`}>{u.role}</span>
                  <span className="label" style={{ fontSize: 10 }}>
                    {u.notify_email && "✉"} {u.notify_sms && "✆"}
                  </span>
                  <button className="btn ghost sm">Remove</button>
                </div>
              ))}
            </div>
          </div>

          <div className="between" style={{ marginTop: 28 }}>
            <button className="btn ghost" style={{ color: "var(--cardinal)" }}>Decommission station</button>
            <div className="row">
              <button className="btn" onClick={onClose}>Cancel</button>
              <button className="btn primary" onClick={onClose}>Save</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DevicesPage() {
  const { data, reload } = useData();
  const DEVICES = data.DEVICES;
  const [open, setOpen] = useState(null);
  const [registering, setRegistering] = useState(false);
  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Field stations</div>
          <h1 className="page-title">Your <em>feeders</em></h1>
        </div>
        <button className="btn primary" onClick={() => setRegistering(true)}>
          <Icon name="plus" className="" /> Register station
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 18 }}>
        {DEVICES.map(d => <DeviceListCard key={d.id} d={d} onClick={setOpen} />)}
      </div>

      {open && <DeviceDetail d={open} onClose={() => setOpen(null)} />}
      {registering && <RegisterDeviceModal onClose={() => setRegistering(false)} onDone={reload} />}
    </>
  );
}
