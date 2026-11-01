// Feeders page — every registered feeder, with its settings
import React, { useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, SelectInput, FormNote, useDialog } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import {
  AV_COLORS, countSightingsBefore, createDevice, deleteDevice, deleteSightingsBefore,
  fetchDeviceToken, fmtRelative, initials, logRefill, rotateDeviceToken, tierInfo, updateDevice,
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

// What powers the station, from the Pi's POWER_SOURCE. A Pi on older code
// sends none, so the card shows nothing rather than guess.
export function Power({ source, battery }) {
  if (source === "mains") {
    return (
      <span className="power" title="Plugged in at the wall">
        <Icon name="plug" className="power-icon" />
        Mains power
      </span>
    );
  }
  if (source !== "battery") return null;
  if (battery == null) {
    return <span className="power" title="This feeder does not report a battery level">Battery</span>;
  }
  const pct = Math.round(battery * 100);
  const level = pct > 50 ? "ok" : pct > 20 ? "low" : "crit";
  return (
    <span className={`power bat-${level}`} title={`Battery ${pct}%`}>
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

/** "40 min", "3 h", "2 days", the way the backend's feed alert words it. */
export function feedAgo(ms) {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 60) return `${Math.max(minutes, 1)} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} days`;
}

/** The card's one plain line about the feed. Null when there is nothing to say. */
export function feedLine(feed, now = Date.now()) {
  if (!feed) return null;
  const since = (t) => feedAgo(now - t.getTime());
  if (feed.state === "out") {
    return feed.lastVisitAt
      ? `Feed may be out. Visits stopped about ${since(feed.lastVisitAt)} ago.`
      : "Feed may be out.";
  }
  if (feed.state === "low") {
    return feed.lastRefillAt
      ? `Feed may be low. Refilled ${since(feed.lastRefillAt)} ago.`
      : "Feed may be low.";
  }
  return feed.lastRefillAt ? `Refilled ${since(feed.lastRefillAt)} ago.` : null;
}

// The feed line, and the Refilled button for whoever manages the feeder. It
// sits outside the card's open button, since a button cannot hold a button.
function FeedRow({ d, canRefill, onRefilled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const line = feedLine(d.feedState);
  if (!line && !canRefill) return null;

  async function refill() {
    setBusy(true);
    setError(null);
    try {
      await logRefill(d.id);
      await onRefilled();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`station-feed feed-${d.feedState?.state || "ok"}`}>
      <span>{error ? `Couldn't log the refill: ${error}` : line || "No refill logged yet."}</span>
      {canRefill && (
        <button type="button" className="btn sm" onClick={refill} disabled={busy}>
          {busy ? "Logging…" : "Refilled"}
        </button>
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

function DeviceListCard({ d, latest, onClick, canRefill, onRefilled }) {
  return (
    <div className="station-card">
      <button type="button" className="station-card-open" onClick={() => onClick(d)}>
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
              <Power source={d.powerSource} battery={d.battery} />
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
      <FeedRow d={d} canRefill={canRefill} onRefilled={onRefilled} />
    </div>
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

// Hand the feeder to another user. Only an owner-role user sees this, since
// only they can list users. The old owner stays on as a member.
function FeederOwner({ d, users, onSaved }) {
  const [ownerId, setOwnerId] = useState(String(d.ownerId));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const current = users.find(u => u.id === d.ownerId);
  const next = users.find(u => String(u.id) === ownerId);
  const options = users.map(u => [String(u.id), u.name]);
  if (!current) options.unshift([String(d.ownerId), "Current owner"]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await updateDevice(d.id, { owner_id: Number(ownerId) });
      await onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="settings-section" style={{ marginTop: 24, display: "grid", gap: 10 }}>
      <div className="label">Owner</div>
      <SelectInput label="Owned by" value={ownerId} onChange={v => { setOwnerId(v); setError(null); }}
        options={options} />
      {next && next.id !== d.ownerId && (
        <>
          <div className="field-help">
            {next.name} becomes the owner. {current ? current.name : "The current owner"} stays
            on as a member. Provision its Pi with {next.name}'s account from now on.
          </div>
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setOwnerId(String(d.ownerId))}>Cancel</button>
            <button className="btn primary" onClick={submit} disabled={busy}>
              {busy ? "Handing over…" : `Make ${next.name} the owner`}
            </button>
          </div>
        </>
      )}
      <FormNote error={error} />
    </div>
  );
}

// The Pi's DEVICE_TOKEN. Rotating it cuts off a lost or replaced Pi, the way a
// password reset cuts off a user.
function FeederToken({ d }) {
  const [token, setToken] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run(action, done) {
    setBusy(true);
    setError(null);
    try {
      setToken((await action(d.id)).token);
      setNote(done);
      setConfirming(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-section" style={{ marginTop: 24, display: "grid", gap: 10 }}>
      <div className="label">Device token</div>
      {token && (
        <>
          <div className="card mono" style={{ padding: "12px 16px", fontSize: 12, wordBreak: "break-all" }}>
            {token}
          </div>
          <div><button className="btn sm" onClick={() => navigator.clipboard?.writeText(token)}>Copy token</button></div>
        </>
      )}
      {confirming ? (
        <>
          <div className="field-help">
            The current token stops working at once, and the Pi stops uploading. Put the new
            token in DEVICE_TOKEN in the Pi's .env, or run scripts/provision_device.py on it.
            Its captures wait in the offline queue until then.
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
            <button className="btn danger" disabled={busy}
              onClick={() => run(rotateDeviceToken, "New token. Give it to the Pi.")}>
              {busy ? "Rotating…" : "Rotate token"}
            </button>
          </div>
        </>
      ) : (
        <div className="row" style={{ gap: 8 }}>
          {!token && (
            <button className="btn" disabled={busy} onClick={() => run(fetchDeviceToken, null)}>Show token</button>
          )}
          <button className="btn" onClick={() => { setConfirming(true); setNote(null); }}>Rotate token…</button>
        </div>
      )}
      <div className="field-help">The Pi signs its uploads with this. Rotate it for a lost or replaced Pi.</div>
      <FormNote error={error} note={note} />
    </div>
  );
}

// "YYYY-MM-DD" from a date input, as local midnight that day.
function localMidnight(value) {
  const [y, m, day] = value.split("-").map(Number);
  return new Date(y, m - 1, day);
}

// Deletes every sighting older than a date, for test captures from before the
// feeder went live. History holds only the newest 100, so it cannot reach them.
// The count comes first, and nothing goes until the owner confirms it.
function ClearOldSightings({ d, onCleared }) {
  const [date, setDate] = useState("");
  const [count, setCount] = useState(null);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function pick(v) { setDate(v); setCount(null); setNote(null); setError(null); }

  async function check() {
    setBusy(true);
    setError(null);
    try {
      setCount((await countSightingsBefore(d.id, localMidnight(date))).count);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await deleteSightingsBefore(d.id, localMidnight(date));
      setNote(`Deleted ${count.toLocaleString()} sightings.`);
      setCount(null);
      await onCleared();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-section" style={{ marginTop: 24, display: "grid", gap: 10 }}>
      <div className="label">Old sightings</div>
      <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <TextInput label="Delete sightings before" type="date" value={date} onChange={pick} />
        </div>
        <button className="btn" onClick={check} disabled={busy || !date}>Check</button>
      </div>
      {count === 0 && <div className="field-help">No sightings before that day.</div>}
      {count > 0 && (
        <>
          <div className="field-help">
            {count.toLocaleString()} sightings from before {localMidnight(date).toLocaleDateString()} and
            their photos will be deleted. This cannot be undone.
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" onClick={() => setCount(null)}>Cancel</button>
            <button className="btn danger" onClick={submit} disabled={busy}>
              {busy ? "Deleting…" : `Delete ${count.toLocaleString()} sightings`}
            </button>
          </div>
        </>
      )}
      <div className="field-help">For test captures from before the feeder went live. To pick single photos, use Select in History.</div>
      <FormNote error={error} note={note} />
    </div>
  );
}

// Removing a feeder with sightings deletes them too. They hold the only copy
// of each photo, so the owner types the feeder's name to confirm.
function RemoveFeeder({ d, onRemoved }) {
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const count = d.allTime;
  const ready = count === 0 || typed.trim() === d.name;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await deleteDevice(d.id, { withSightings: count > 0 });
      await onRemoved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="settings-section" style={{ marginTop: 24, display: "grid", gap: 10 }}>
      <div className="label">Remove</div>
      {confirming ? (
        <>
          <div className="field-help">
            {count > 0
              ? `Remove ${d.name} and its ${count.toLocaleString()} sightings? Their photos are deleted too, and cannot be recovered.`
              : `Remove ${d.name}? It has no sightings.`}
            {" "}If its Pi is still running, its uploads stop.
          </div>
          {count > 0 && (
            <TextInput label={`Type ${d.name} to confirm`} value={typed} onChange={setTyped} />
          )}
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" onClick={() => { setConfirming(false); setTyped(""); }}>Cancel</button>
            <button className="btn danger" onClick={submit} disabled={busy || !ready}>
              {busy ? "Removing…" : `Remove ${d.name}`}
            </button>
          </div>
        </>
      ) : (
        <div><button className="btn" onClick={() => setConfirming(true)}>Remove feeder…</button></div>
      )}
      <FormNote error={error} />
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
              {/* Keyed on the owner, so a handover refetches the list. */}
              <FeederRecipients key={d.ownerId} d={d} me={data.ME} users={data.USERS} onLostAccess={reload} />
              {data.USERS.length > 0 && (
                <FeederOwner key={`owner-${d.ownerId}`} d={d} users={data.USERS} onSaved={reload} />
              )}
              <FeederToken d={d} />
              {d.allTime > 0 && <ClearOldSightings d={d} onCleared={reload} />}
              {/* The reload drops the feeder from the list, which closes this dialog. */}
              <RemoveFeeder d={d} onRemoved={reload} />
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
  const { DEVICES, SIGHTINGS, ME } = data;
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
          {DEVICES.map(d => (
            <DeviceListCard key={d.id} d={d} latest={latestBy.get(d.id)} onClick={d => setOpenId(d.id)}
              canRefill={!!ME && canManageFeeder(d, ME)} onRefilled={reload} />
          ))}
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
