// Feeders page — every registered feeder, with its settings
import React, { useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote, useDialog } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import { createDevice, fmtRelative } from "./data.js";

function RegisterDeviceModal({ onClose, onDone }) {
  const [form, setForm] = useState({ name: "", city: "", state: "", feed_type: "" });
  const [token, setToken] = useState(null); // device token, shown once after create
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  async function submit() {
    if (!form.name) { setError("A feeder name is required."); return; }
    setBusy(true);
    setError(null);
    try {
      const body = { name: form.name, city: form.city || null, state: form.state || null, feed_type: form.feed_type || null };
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
        title="Feeder registered"
        subtitle="Copy this device token now — it's shown only once and is needed to provision the Pi."
        onClose={onClose}
        footer={<button className="btn primary" onClick={onClose}>Done</button>}
      >
        <div className="card mono" style={{ padding: "12px 16px", fontSize: 12, wordBreak: "break-all" }}>
          {token}
        </div>
        <button className="btn" onClick={() => navigator.clipboard?.writeText(token)}>Copy token</button>
      </Modal>
    );
  }

  return (
    <Modal
      title="Register a feeder"
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
      <FormNote error={error} />
    </Modal>
  );
}

const STATUS = {
  online: { cls: "on", label: "Online" },
  warn: { cls: "warn", label: "Low signal" },
  offline: { cls: "off", label: "Offline" },
};

export function DeviceStatus({ d }) {
  const st = STATUS[d.status] || STATUS.offline;
  return (
    <span className={`device-status status-${st.cls}`}>
      <span className={`dot ${st.cls}`} />
      {st.label}
    </span>
  );
}

// Battery only for stations that report one. A mains-powered Pi sends null.
function Battery({ value }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const level = pct > 50 ? "ok" : pct > 20 ? "low" : "crit";
  return (
    <span className={`battery bat-${level}`} title={`Battery ${pct}%`}>
      <span className="bat-bar"><span className="bat-fill" style={{ width: `${pct}%` }} /></span>
      <span className="tnum">{pct}%</span>
    </span>
  );
}

function DeviceListCard({ d, latest, onClick }) {
  return (
    <button type="button" className="station-card" onClick={() => onClick(d)}>
      <div className="station-shot">
        {latest ? (
          <>
            {/* large: the card is 300 px wide or more, past what a thumbnail covers. */}
            <SightingImage sighting={latest} large />
            <span className="tile-badge tile-badge-l">Last capture · {fmtRelative(latest.datetime)}</span>
          </>
        ) : (
          <div className="station-shot-empty">No captures yet</div>
        )}
      </div>
      <div className="card-pad">
        <div className="between">
          <div>
            <div className="device-name">{d.name}</div>
            <div className="device-loc">
              {[d.city !== "—" && [d.city, d.state].filter(Boolean).join(", "), d.feed !== "—" && d.feed]
                .filter(Boolean).join(" · ") || "No location set"}
            </div>
          </div>
          <div className="station-card-status">
            <DeviceStatus d={d} />
            <Battery value={d.battery} />
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
        <div className="station-seen">Last heard from {d.lastSeen}</div>
      </div>
    </button>
  );
}

function DeviceDetail({ d, onClose }) {
  const { data } = useData();
  const USERS = data.USERS;
  const panelRef = useRef(null);
  useDialog(onClose, panelRef);

  // Recipients are configured per-user (notify_email in Users), so we
  // show the owners/viewers who currently receive alerts — read-only until the
  // per-device recipient endpoint lands (there's no GET for it yet).
  const recipients = USERS.filter(u => u.notify_email);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}
        ref={panelRef} role="dialog" aria-modal="true" aria-label={`${d.name} settings`} tabIndex={-1}>
        <button className="modal-close" onClick={onClose} aria-label="Close dialog"><Icon name="x" className="" /></button>
        <div style={{ padding: "28px 32px" }}>
          <div className="label" style={{ marginBottom: 8 }}>Feeder settings</div>
          <h2 className="dialog-title">{d.name}</h2>
          <div className="dialog-sub">{d.city}, {d.state}</div>

          <div className="settings-section" style={{ marginTop: 24 }}>
            <div className="label" style={{ marginBottom: 12 }}>Notification recipients</div>
            {recipients.length > 0 ? (
              <div className="card">
                {recipients.map(u => (
                  <div className="user-row" key={u.id}>
                    <div className="av-lg" style={{ background: u.avBg }}>{u.av}</div>
                    <div>
                      <div style={{ fontSize: 13.5, fontWeight: 700 }}>{u.name}</div>
                      <div style={{ fontSize: 12.5, color: "var(--mu)" }}>{u.email}</div>
                    </div>
                    <span className={`role-badge role-${u.role}`}>{u.role}</span>
                    <span className="label" style={{ fontSize: 10 }}>
                      {u.notify_email && "✉"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="field-help">No users have notifications enabled. Turn them on per user under Users.</div>
            )}
            <div className="field-help" style={{ marginTop: 8 }}>
              Recipients follow each user's notification settings. Per-feeder recipient lists are coming soon.
            </div>
          </div>

          <div className="row" style={{ marginTop: 28, justifyContent: "flex-end" }}>
            <button className="btn primary" onClick={onClose}>Done</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DevicesPage() {
  const { data, reload } = useData();
  const { DEVICES, SIGHTINGS } = data;
  // Newest capture with a photo per feeder; SIGHTINGS is newest-first.
  const latestBy = new Map();
  for (const s of SIGHTINGS) {
    if (s.hasImage && !latestBy.has(s.device.id)) latestBy.set(s.device.id, s);
  }
  const [open, setOpen] = useState(null);
  const [registering, setRegistering] = useState(false);
  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">Your stations</div>
          <h1 className="page-title">Feeders</h1>
        </div>
        <button className="btn primary" onClick={() => setRegistering(true)}>
          <Icon name="plus" className="" /> Register feeder
        </button>
      </div>

      {DEVICES.length > 0 ? (
        <div className="station-grid">
          {DEVICES.map(d => <DeviceListCard key={d.id} d={d} latest={latestBy.get(d.id)} onClick={setOpen} />)}
        </div>
      ) : (
        <Empty
          icon="📡"
          title="No feeders registered"
          hint="Register a feeder to get a device token and start receiving sightings."
          action={<button className="btn primary sm" onClick={() => setRegistering(true)}>
            <Icon name="plus" className="" /> Register feeder
          </button>}
        />
      )}

      {open && <DeviceDetail d={open} onClose={() => setOpen(null)} />}
      {registering && <RegisterDeviceModal onClose={() => setRegistering(false)} onDone={reload} />}
    </>
  );
}
