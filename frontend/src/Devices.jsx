// Feeders page — every registered feeder, with its settings
import React, { useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote, useDialog } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import {
  AV_COLORS, createDevice, fmtRelative, initials, tierInfo, updateDevice,
} from "./data.js";
import { canManageFeeder, useFeederAccess } from "./feederAccess.js";

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

/** "Last 24 h: 41 GPU, 3 Pi, 0 none". Claude only shows once it has answered. */
export function tierMixText(mix) {
  const { gpu, local, cloud, none } = mix.counts;
  const parts = [`${gpu} ${tierInfo("gpu").short}`, `${local} ${tierInfo("local").short}`];
  if (cloud > 0) parts.push(`${cloud} ${tierInfo("cloud").short}`);
  parts.push(`${none} none`);
  return `Last ${mix.hours} h: ${parts.join(", ")}`;
}

function TierMix({ mix }) {
  if (!mix) return null;
  return (
    <div className="station-tiers">
      <span className="tnum">{tierMixText(mix)}</span>
      {mix.tier2Down && (
        <span className="station-tiers-warn"
          title={`${mix.tier2Missed} of ${mix.tier2Asked} captures got no answer from the GPU server.`}>
          GPU not answering
        </span>
      )}
    </div>
  );
}

// mapDevice shows an empty city or feed type as "—". The form wants "".
const blank = v => (v === "—" ? "" : v);

function locationText(d) {
  return [d.city !== "—" && [d.city, d.state].filter(Boolean).join(", "), d.feed !== "—" && d.feed]
    .filter(Boolean).join(" · ") || "No location set";
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
            <div className="device-loc">{locationText(d)}</div>
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
        <TierMix mix={d.tierMix} />
        <div className="station-seen">Last heard from {d.lastSeen}</div>
      </div>
    </button>
  );
}

// Name, location and feed type. The weather lookup geocodes the city and state.
function FeederDetailsForm({ d, onSaved }) {
  const [form, setForm] = useState({
    name: d.name, city: blank(d.city), state: d.state, feed_type: blank(d.feed),
  });
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = k => v => { setForm(f => ({ ...f, [k]: v })); setNote(null); };

  async function save() {
    if (!form.name.trim()) { setError("A feeder name is required."); return; }
    setBusy(true);
    setError(null);
    try {
      await updateDevice(d.id, {
        name: form.name.trim(), city: form.city.trim(), state: form.state.trim(),
        feed_type: form.feed_type.trim(),
      });
      await onSaved();
      setNote("Saved.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-section" style={{ marginTop: 24, display: "grid", gap: 14 }}>
      <div className="label">Details</div>
      <TextInput label="Name" value={form.name} onChange={set("name")} />
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
        <TextInput label="City" value={form.city} onChange={set("city")} />
        <TextInput label="State" value={form.state} onChange={set("state")} />
      </div>
      <TextInput label="Bait / feed type" value={form.feed_type} onChange={set("feed_type")}
        help="Each sighting's weather comes from the city and state." />
      <FormNote error={error} note={note} />
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save details"}</button>
      </div>
    </div>
  );
}

function RecipientRow({ u, badge, users, action }) {
  const known = users.find(x => x.id === u.id);
  return (
    <div className="user-row">
      <div className="av-lg" style={{ background: known?.avBg || AV_COLORS[u.id % AV_COLORS.length] }}>
        {known?.av || initials(u.name)}
      </div>
      <div>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{u.name}</div>
        <div style={{ fontSize: 12.5, color: "var(--mu)" }}>{u.email}</div>
      </div>
      <span className={`role-badge role-${badge === "owner" ? "owner" : "viewer"}`}>{badge}</span>
      <span className="label" style={{ fontSize: 10 }}>✉ {u.notify_email ? "ON" : "OFF"}</span>
      {action || <span />}
    </div>
  );
}

// The owner and the members see the feeder and get its alerts. They are the
// people backend/notifications/service.py sends to. Members are added by
// email, because a viewer who owns a feeder cannot list users.
function FeederRecipients({ d, me, users, onLostAccess }) {
  const { access, loaded, error, share, unshare } = useFeederAccess([d.id]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const a = access.get(d.id);

  async function add() {
    if (!email.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await share(d.id, { email: email.trim() });
      setEmail("");
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(u) {
    setBusy(true);
    setActionError(null);
    try {
      await unshare(d.id, u.id);
      if (u.id === me.id) await onLostAccess();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const listed = a ? new Set([a.owner.id, ...a.members.map(m => m.id)]) : new Set();
  const suggestions = users.filter(u => !listed.has(u.id));

  return (
    <div className="settings-section" style={{ marginTop: 24 }}>
      <div className="label" style={{ marginBottom: 12 }}>Who sees this feeder</div>
      {error && <div className="field-help field-error">Couldn't load members: {error}</div>}
      {!error && !loaded && <div className="field-help">Loading…</div>}
      {a && (
        <div className="card">
          <RecipientRow u={a.owner} badge="owner" users={users} />
          {a.members.map(u => (
            <RecipientRow key={u.id} u={u} badge="member" users={users}
              action={<button className="btn ghost sm" disabled={busy} onClick={() => remove(u)}
                aria-label={`Remove ${u.name}`}>Remove</button>} />
          ))}
        </div>
      )}
      <div className="field-help" style={{ marginTop: 8 }}>
        These people see its sightings and get its alerts. Each person turns email
        and push on or off in their own Settings.
      </div>
      <div className="row" style={{ marginTop: 12, gap: 8, alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <TextInput label="Share with" type="email" placeholder="Their account email"
            value={email} onChange={setEmail} list={`share-${d.id}`} />
          <datalist id={`share-${d.id}`}>
            {suggestions.map(u => <option key={u.id} value={u.email}>{u.name}</option>)}
          </datalist>
        </div>
        <button className="btn" onClick={add} disabled={busy || !email.trim()}>Add</button>
      </div>
      <FormNote error={actionError} />
    </div>
  );
}

function DeviceDetail({ d, onClose }) {
  const { data, reload } = useData();
  const panelRef = useRef(null);
  useDialog(onClose, panelRef);
  const manage = canManageFeeder(d, data.ME);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}
        ref={panelRef} role="dialog" aria-modal="true" aria-label={`${d.name} settings`} tabIndex={-1}>
        <button className="modal-close" onClick={onClose} aria-label="Close dialog"><Icon name="x" className="" /></button>
        <div style={{ padding: "28px 32px" }}>
          <div className="label" style={{ marginBottom: 8 }}>Feeder settings</div>
          <h2 className="dialog-title">{d.name}</h2>
          <div className="dialog-sub">{locationText(d)}</div>

          {manage ? (
            <>
              <FeederDetailsForm d={d} onSaved={reload} />
              <FeederRecipients d={d} me={data.ME} users={data.USERS} onLostAccess={reload} />
            </>
          ) : (
            <div className="field-help" style={{ marginTop: 24 }}>
              This feeder is shared with you. Only its owner can change its details or who sees it.
            </div>
          )}

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
  // An id, not the feeder, so a save or a reload shows the new values. A
  // feeder that drops out of the list closes the dialog.
  const [openId, setOpenId] = useState(null);
  const open = DEVICES.find(d => d.id === openId);
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
          {DEVICES.map(d => <DeviceListCard key={d.id} d={d} latest={latestBy.get(d.id)} onClick={d => setOpenId(d.id)} />)}
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

      {open && <DeviceDetail d={open} onClose={() => setOpenId(null)} />}
      {registering && <RegisterDeviceModal onClose={() => setRegistering(false)} onDone={reload} />}
    </>
  );
}
