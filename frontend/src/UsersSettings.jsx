// Users page + Settings page
import React, { useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { useAppearance } from "./Appearance.jsx";
import { Modal, TextInput, SelectInput, FormNote } from "./Modal.jsx";
import {
  saveMe, savePreferences, createUser, updateUser, changePassword,
} from "./data.js";
import {
  checkRequired, checkEmail, checkPhone, checkPassword, collect, hasErrors,
} from "./validate.js";

// Admin-creates-with-temp-password: there's no SendGrid email-invite flow yet,
// so the owner sets a temporary password and shares it out of band.
function InviteUserModal({ onClose, onDone }) {
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "viewer", phone: "" });
  const [error, setError] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  function validate() {
    return collect({
      name: checkRequired(form.name, "Name"),
      email: checkEmail(form.email),
      password: checkPassword(form.password, { label: "Temporary password" }),
      phone: checkPhone(form.phone),
    });
  }

  async function submit() {
    const errs = validate();
    setFieldErr(errs);
    if (hasErrors(errs)) { setError(null); return; }
    setBusy(true);
    setError(null);
    try {
      await createUser({
        name: form.name.trim(), email: form.email.trim(), password: form.password,
        role: form.role, phone: form.phone.trim() || null,
      });
      await onDone();
      onClose();
    } catch (e) {
      setError(e.status === 409 ? "That email is already registered." : e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Invite a user"
      subtitle="Set a temporary password and share it with them — they can change it in Settings."
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Adding…" : "Add user"}</button>
      </>}
    >
      <TextInput label="Name" value={form.name} onChange={set("name")} error={fieldErr.name} />
      <TextInput label="Email" type="email" value={form.email} onChange={set("email")} error={fieldErr.email} />
      <TextInput label="Temporary password" type="password" value={form.password} onChange={set("password")}
        help="At least 8 characters." error={fieldErr.password} />
      <TextInput label="Phone" help="Optional. E.164 format for SMS." value={form.phone} onChange={set("phone")}
        error={fieldErr.phone} />
      <SelectInput label="Role" value={form.role} onChange={set("role")}
        options={[["viewer", "Viewer"], ["owner", "Owner"]]} />
      <FormNote error={error} />
    </Modal>
  );
}

// Edit is limited to the fields UpdateUser accepts (name/phone/notify/email).
// Role changes need a dedicated route and stay read-only here.
function EditUserModal({ user, onClose, onDone }) {
  const [form, setForm] = useState({
    name: user.name, phone: user.phone === "—" ? "" : user.phone, email: user.email,
    notify_email: user.notify_email, notify_sms: user.notify_sms,
  });
  const [error, setError] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  async function submit() {
    const errs = collect({
      name: checkRequired(form.name, "Name"),
      email: checkEmail(form.email),
      phone: checkPhone(form.phone),
    });
    setFieldErr(errs);
    if (hasErrors(errs)) { setError(null); return; }
    setBusy(true);
    setError(null);
    try {
      await updateUser(user.id, {
        name: form.name.trim(), phone: form.phone.trim() || null, email: form.email.trim(),
        notify_email: form.notify_email, notify_sms: form.notify_sms,
      });
      await onDone();
      onClose();
    } catch (e) {
      setError(e.status === 409 ? "That email is already registered." : e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Edit ${user.name}`}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </>}
    >
      <TextInput label="Name" value={form.name} onChange={set("name")} error={fieldErr.name} />
      <TextInput label="Email" type="email" value={form.email} onChange={set("email")} error={fieldErr.email} />
      <TextInput label="Phone" help="E.164 format for SMS." value={form.phone} onChange={set("phone")} error={fieldErr.phone} />
      <SelectInput label="Role" value={user.role} onChange={() => {}}
        options={[["viewer", "Viewer"], ["owner", "Owner"]]} />
      <div className="field-help" style={{ marginTop: -6 }}>Role changes aren't supported here yet.</div>
      <label className="row" style={{ gap: 8, alignItems: "center" }}>
        <input type="checkbox" checked={form.notify_email} onChange={e => set("notify_email")(e.target.checked)} />
        <span>Email notifications</span>
      </label>
      <label className="row" style={{ gap: 8, alignItems: "center" }}>
        <input type="checkbox" checked={form.notify_sms} onChange={e => set("notify_sms")(e.target.checked)} />
        <span>SMS notifications</span>
      </label>
      <FormNote error={error} />
    </Modal>
  );
}

export function UsersPage() {
  const { data, reload } = useData();
  const USERS = data.USERS;
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState(null);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>People who watch your feeders</div>
          <h1 className="page-title">Users &amp; <em>roles</em></h1>
        </div>
        <button className="btn primary" onClick={() => setInviting(true)}>
          <Icon name="plus" className="" /> Invite user
        </button>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">Members</div>
          <span className="label">{USERS.length} people</span>
        </div>
        {USERS.map(u => (
          <div className="user-row" key={u.id}>
            <div className="av-lg" style={{ background: u.avBg }}>{u.av}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{u.name}</div>
              <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 2 }}>
                {u.email} · {u.phone}
              </div>
            </div>
            <span className={`role-badge role-${u.role}`}>{u.role}</span>
            <span className="label" style={{ fontSize: 10, display: "flex", gap: 10 }}>
              <span style={{ color: u.notify_email ? "var(--forest)" : "var(--ink-mute)" }}>
                ✉ {u.notify_email ? "ON" : "OFF"}
              </span>
              <span style={{ color: u.notify_sms ? "var(--forest)" : "var(--ink-mute)" }}>
                ✆ {u.notify_sms ? "ON" : "OFF"}
              </span>
            </span>
            <button className="btn ghost sm" onClick={() => setEditing(u)}>Edit</button>
          </div>
        ))}
      </div>

      {inviting && <InviteUserModal onClose={() => setInviting(false)} onDone={reload} />}
      {editing && <EditUserModal user={editing} onClose={() => setEditing(null)} onDone={reload} />}
    </>
  );
}

const SETTINGS_SECTIONS = [
  { id: "account", label: "Account" },
  { id: "notifications", label: "Notifications" },
  { id: "classification", label: "Classification" },
  { id: "integrations", label: "API keys" },
  { id: "appearance", label: "Appearance" },
];

function Toggle({ on, onChange }) {
  return <button className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} aria-pressed={on} />;
}

function Field({ label, help, children }) {
  return (
    <div className="field">
      <div>
        <div className="field-label">{label}</div>
        {help && <div className="field-help">{help}</div>}
      </div>
      <div className="field-control">{children}</div>
    </div>
  );
}

// Small saved/saving/error indicator shown in each section header.
function SaveStatus({ status }) {
  if (!status) return null;
  const map = {
    saving: { text: "Saving…", color: "var(--ink-soft)" },
    saved: { text: "✓ Saved", color: "var(--forest)" },
    error: { text: "Couldn't save", color: "var(--cardinal)" },
  };
  const s = map[status.kind] || map.saved;
  return (
    <span className="label" style={{ color: s.color }} title={status.msg || ""}>
      {s.text}
    </span>
  );
}

const TIERS = [
  ["local", "Tier 1 — Local", "iNatVision TFLite on the Pi. Offline-friendly.", "PI ONLY"],
  ["gpu", "Tier 2 — LAN GPU", "Forwarded to RTX 5080. Higher accuracy.", "WIFI"],
  ["cloud", "Tier 3 — Cloud", "Anthropic Claude multimodal. Hard cases.", "INTERNET"],
  ["auto", "Auto", "Try local first. Escalate when confidence falls below threshold.", "RECOMMENDED"],
];

// Self password change — current password is required (verified server-side).
function ChangePasswordModal({ userId, onClose }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!cur) { setError("Enter your current password."); return; }
    const pwErr = checkPassword(next, { label: "New password" });
    if (pwErr) { setError(pwErr); return; }
    if (next !== confirm) { setError("New passwords don't match."); return; }
    setBusy(true);
    setError(null);
    try {
      await changePassword(userId, { current_password: cur, new_password: next });
      onClose(true);
    } catch (e) {
      setError(e.status === 400 ? "Your current password is incorrect." : e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Change password"
      onClose={() => onClose(false)}
      footer={<>
        <button className="btn" onClick={() => onClose(false)}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Saving…" : "Update password"}</button>
      </>}
    >
      <TextInput label="Current password" type="password" value={cur} onChange={setCur} />
      <TextInput label="New password" type="password" value={next} onChange={setNext} />
      <TextInput label="Confirm new password" type="password" value={confirm} onChange={setConfirm} />
      <FormNote error={error} />
    </Modal>
  );
}

export function SettingsPage() {
  const { data, patch } = useData();
  const me = data.ME;
  const prefs = data.PREFERENCES;
  const { appearance, update: updateAppearance } = useAppearance();

  const [section, setSection] = useState("account");
  const [status, setStatus] = useState(null);
  const [changingPassword, setChangingPassword] = useState(false);

  // Account text fields buffer locally and persist on blur.
  const [name, setName] = useState(me.name);
  const [phone, setPhone] = useState(me.phone);
  const [email, setEmail] = useState(me.email);
  const [acctErr, setAcctErr] = useState({});

  // Validate a field on blur; only persist when it's valid + actually changed.
  function commitField(key, value, current, errMsg) {
    if (errMsg) {
      setAcctErr(e => ({ ...e, [key]: errMsg }));
      return;
    }
    setAcctErr(e => ({ ...e, [key]: null }));
    if (value.trim() !== current) saveUser({ [key]: value.trim() });
  }

  // Sliders buffer locally for smooth dragging, then commit on release.
  const [quiet, setQuiet] = useState(prefs.quiet_interval_seconds);
  const [thresh, setThresh] = useState(prefs.escalation_threshold);

  async function saveUser(patchObj) {
    setStatus({ kind: "saving" });
    try {
      const updated = await saveMe(me.id, patchObj);
      patch({ ME: updated });
      setStatus({ kind: "saved" });
    } catch (e) {
      setStatus({ kind: "error", msg: e.message });
    }
  }

  async function savePrefs(patchObj) {
    setStatus({ kind: "saving" });
    try {
      const updated = await savePreferences(patchObj);
      patch({ PREFERENCES: updated });
      setStatus({ kind: "saved" });
    } catch (e) {
      setStatus({ kind: "error", msg: e.message });
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Station preferences</div>
          <h1 className="page-title"><em>Settings</em></h1>
        </div>
      </div>

      <div className="settings-layout">
        <nav className="settings-nav">
          {SETTINGS_SECTIONS.map(s => (
            <button key={s.id} className={section === s.id ? "active" : ""} onClick={() => setSection(s.id)}>
              {s.label}
            </button>
          ))}
        </nav>

        <div>
          {section === "account" && (
            <div className="settings-section">
              <div className="between">
                <h3>Account details</h3>
                <SaveStatus status={status} />
              </div>
              <p className="lead">How you appear to other users and how the app reaches you.</p>
              <Field label="Name">
                <input type="text" value={name} aria-label="Name"
                  aria-invalid={acctErr.name ? "true" : undefined}
                  onChange={e => setName(e.target.value)}
                  onBlur={() => commitField("name", name, me.name, checkRequired(name, "Name"))} />
                {acctErr.name && <div className="field-help" style={{ color: "var(--cardinal)" }}>{acctErr.name}</div>}
              </Field>
              <Field label="Email" help="Used for login and email notifications.">
                <input type="email" value={email} aria-label="Email"
                  aria-invalid={acctErr.email ? "true" : undefined}
                  onChange={e => setEmail(e.target.value)}
                  onBlur={() => commitField("email", email, me.email, checkEmail(email))} />
                {acctErr.email && <div className="field-help" style={{ color: "var(--cardinal)" }}>{acctErr.email}</div>}
              </Field>
              <Field label="Phone" help="E.164 format. Required for SMS.">
                <input type="text" value={phone} aria-label="Phone"
                  aria-invalid={acctErr.phone ? "true" : undefined}
                  onChange={e => setPhone(e.target.value)}
                  onBlur={() => commitField("phone", phone, me.phone, checkPhone(phone))} />
                {acctErr.phone && <div className="field-help" style={{ color: "var(--cardinal)" }}>{acctErr.phone}</div>}
              </Field>
              <Field label="Password">
                <button className="btn" onClick={() => setChangingPassword(true)}>Change password…</button>
              </Field>
            </div>
          )}

          {section === "notifications" && (
            <div className="settings-section">
              <div className="between">
                <h3>Notifications</h3>
                <SaveStatus status={status} />
              </div>
              <p className="lead">When a bird is identified, who gets notified, and how often.</p>

              <Field label="Channels" help="You can toggle each independently — at least one must be on to receive alerts.">
                <div className="card">
                  <div className="card-pad" style={{ padding: "4px 16px" }}>
                    <div className="toggle-row">
                      <Toggle on={me.notify_email} onChange={v => saveUser({ notify_email: v })} />
                      <div className="toggle-row-text">
                        <div className="toggle-row-title">Email — {me.email}</div>
                        <div className="toggle-row-sub">Inline thumbnail + species card + Wikipedia link</div>
                      </div>
                      <span className="label">VIA SENDGRID</span>
                    </div>
                    <div className="toggle-row">
                      <Toggle on={me.notify_sms} onChange={v => saveUser({ notify_sms: v })} />
                      <div className="toggle-row-text">
                        <div className="toggle-row-title">SMS — {me.phone || "no phone on file"}</div>
                        <div className="toggle-row-sub">Concise text + MMS image where supported</div>
                      </div>
                      <span className="label">VIA TWILIO</span>
                    </div>
                  </div>
                </div>
              </Field>

              <Field label="Quiet interval" help="Minimum seconds between notifications per device. Prevents spam during a long visit.">
                <div>
                  <input type="range" min="10" max="600" step="10" value={quiet}
                    onChange={e => setQuiet(Number(e.target.value))}
                    onMouseUp={() => savePrefs({ quiet_interval_seconds: quiet })}
                    onTouchEnd={() => savePrefs({ quiet_interval_seconds: quiet })}
                    onKeyUp={() => savePrefs({ quiet_interval_seconds: quiet })}
                    style={{ width: "100%" }} />
                  <div className="between" style={{ marginTop: 6 }}>
                    <span className="label">10s</span>
                    <span className="display-i tnum" style={{ fontSize: 22 }}>{quiet}s</span>
                    <span className="label">10m</span>
                  </div>
                </div>
              </Field>

              <Field label="Notify only for new species"
                help="When on, you'll only be alerted the first time a species shows up.">
                <Toggle on={prefs.notify_new_species_only}
                  onChange={v => savePrefs({ notify_new_species_only: v })} />
              </Field>
            </div>
          )}

          {section === "classification" && (
            <div className="settings-section">
              <div className="between">
                <h3>Classification</h3>
                <SaveStatus status={status} />
              </div>
              <p className="lead">Default tier for new stations. Per-station overrides live in Devices.</p>

              <Field label="Default tier">
                <div className="tier-stack">
                  {TIERS.map(([k, n, d, b], i) => (
                    <div key={k} className={`tier-card ${prefs.default_tier === k ? "selected" : ""}`}
                      onClick={() => savePrefs({ default_tier: k })}>
                      <div className="tier-num">{i + 1}</div>
                      <div>
                        <div className="tier-name">{n}</div>
                        <div className="tier-desc">{d}</div>
                      </div>
                      <span className="tier-badge">{b}</span>
                    </div>
                  ))}
                </div>
              </Field>

              <Field label="Auto-escalation threshold"
                help="When in Auto mode, fall back to a higher tier if confidence is below this.">
                <div>
                  <input type="range" min="40" max="95" step="1" value={thresh}
                    onChange={e => setThresh(Number(e.target.value))}
                    onMouseUp={() => savePrefs({ escalation_threshold: thresh })}
                    onTouchEnd={() => savePrefs({ escalation_threshold: thresh })}
                    onKeyUp={() => savePrefs({ escalation_threshold: thresh })}
                    style={{ width: "100%" }} />
                  <div className="between" style={{ marginTop: 6 }}>
                    <span className="label">40%</span>
                    <span className="display-i tnum" style={{ fontSize: 22 }}>{thresh}%</span>
                    <span className="label">95%</span>
                  </div>
                </div>
              </Field>

              <Field label="Debounce window"
                help="Skip duplicate captures within this window of a confirmed sighting.">
                <select value={String(prefs.debounce_seconds)}
                  onChange={e => savePrefs({ debounce_seconds: Number(e.target.value) })}>
                  <option value="10">10 seconds</option>
                  <option value="30">30 seconds</option>
                  <option value="60">60 seconds</option>
                  <option value="120">2 minutes</option>
                </select>
              </Field>
            </div>
          )}

          {section === "integrations" && (
            <div className="settings-section">
              <h3>API keys</h3>
              <p className="lead">Stored as environment variables on the gaming PC. Never sent to the Pi —
                and never editable from the browser. Shown masked for reference only.</p>
              <Field label="Anthropic Claude" help="Powers Tier 3 cloud classification.">
                <input type="password" value="sk-ant-•••••••••••••••••0a9b" readOnly />
              </Field>
              <Field label="SendGrid" help="Outbound transactional email.">
                <input type="password" value="SG.•••••••••••••••••8f2c" readOnly />
              </Field>
              <Field label="Twilio" help="SMS + MMS for mobile alerts.">
                <input type="text" value="AC1234567890abcdef" readOnly />
                <input type="password" value="••••••••••••••••" readOnly style={{ marginTop: 6 }} />
              </Field>
            </div>
          )}

          {section === "appearance" && (
            <div className="settings-section">
              <h3>Appearance</h3>
              <p className="lead">Visual preferences for the field journal interface. Saved in this browser.</p>
              <Field label="Theme">
                <div className="row">
                  <button className={`btn ${appearance.theme === "day" ? "primary" : ""}`}
                    onClick={() => updateAppearance({ theme: "day" })}>Day</button>
                  <button className={`btn ${appearance.theme === "dusk" ? "primary" : ""}`}
                    onClick={() => updateAppearance({ theme: "dusk" })}>Dusk</button>
                </div>
              </Field>
              <Field label="Accent" help="Primary highlight color across the app.">
                <select value={appearance.accent}
                  onChange={e => updateAppearance({ accent: e.target.value })}>
                  <option value="cardinal">Cardinal</option>
                  <option value="forest">Forest</option>
                  <option value="yolk">Yolk</option>
                  <option value="plum">Plum</option>
                </select>
              </Field>
              <Field label="Display font" help="Used for headings and large numerals.">
                <select value={appearance.displayFont}
                  onChange={e => updateAppearance({ displayFont: e.target.value })}>
                  <option value="newsreader">Newsreader</option>
                  <option value="instrument">Instrument Serif</option>
                  <option value="playfair">Playfair Display</option>
                  <option value="eb">EB Garamond</option>
                </select>
              </Field>
              <Field label="Density">
                <select value={appearance.density}
                  onChange={e => updateAppearance({ density: e.target.value })}>
                  <option value="compact">Compact</option>
                  <option value="comfortable">Comfortable</option>
                  <option value="spacious">Spacious</option>
                </select>
              </Field>
            </div>
          )}
        </div>
      </div>

      {changingPassword && (
        <ChangePasswordModal
          userId={me.id}
          onClose={(saved) => {
            setChangingPassword(false);
            if (saved) setStatus({ kind: "saved" });
          }}
        />
      )}
    </>
  );
}
