// Settings page. The Users page is in Users.jsx.
import React, { useEffect, useState } from "react";
import { useData } from "./DataContext.jsx";
import { useAppearance } from "./Appearance.jsx";
import { PALETTES, themeTokens } from "./themes.js";
import { Modal, TextInput, SelectInput, FormNote } from "./Modal.jsx";
import {
  currentSubscription, disablePush, enablePush, fetchPushConfig, permission,
  pushSupported,
} from "./push.js";
import {
  saveMe, savePreferences, changePassword,
  fetchStorage, formatBytes,
} from "./data.js";
import {
  checkRequired, checkEmail, checkPassword,
} from "./validate.js";
import { GROUPS } from "./animals.js";

// How often one feeder may push about one animal group.
export const ANIMAL_INTERVALS = [
  [900, "15 minutes"], [1800, "30 minutes"], [3600, "1 hour"], [7200, "2 hours"], [21600, "6 hours"],
];

const SETTINGS_SECTIONS = [
  { id: "account", label: "Account" },
  { id: "notifications", label: "Notifications" },
  { id: "appearance", label: "Appearance" },
  { id: "storage", label: "Storage" },
];

function Toggle({ on, onChange, disabled = false }) {
  return (
    <button className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)}
      aria-pressed={on} disabled={disabled} />
  );
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
    saving: { text: "Saving…", color: "var(--mu)" },
    saved: { text: "✓ Saved", color: "var(--ok)" },
    error: { text: "Couldn't save", color: "var(--bad)" },
  };
  const s = map[status.kind] || map.saved;
  return (
    <span className="label" style={{ color: s.color }} title={status.msg || ""}>
      {s.text}
    </span>
  );
}

/**
 * Browser push channel row — FLEDGE Phase 7.
 *
 * Unlike email this is not a user column: the subscription belongs to
 * *this browser*, so the toggle reads its live state from the service worker
 * rather than from `data.ME`. Which also means it must handle four different
 * kinds of "off": unsupported browser, no service worker (dev), no server keys,
 * and permission denied — each with a different thing for the user to do about
 * it.
 */
function PushChannelRow() {
  const [state, setState] = useState({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!pushSupported()) {
        if (!cancelled) setState({ status: "unsupported" });
        return;
      }
      const [config, subscription] = await Promise.all([
        fetchPushConfig(), currentSubscription(),
      ]);
      if (cancelled) return;
      setState({
        status: config.enabled ? "ready" : "server-disabled",
        publicKey: config.public_key,
        subscribed: !!subscription,
      });
    })();
    return () => { cancelled = true; };
  }, []);

  async function toggle(on) {
    setBusy(true);
    setError(null);
    try {
      if (on) await enablePush(state.publicKey);
      else await disablePush();
      setState((s) => ({ ...s, subscribed: on }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const denied = permission() === "denied";
  const sub = state.status === "ready" && !!state.subscribed;

  let note;
  if (state.status === "loading") note = "Checking…";
  else if (state.status === "unsupported") note = "This browser can't receive web push.";
  else if (state.status === "server-disabled") note = "No VAPID keys on the server — see .env.example.";
  else if (denied && !sub) note = "Blocked in your browser's site settings.";
  else if (sub) note = "Alerts arrive even with the app closed.";
  else note = "Instant alerts on this device, no email needed.";

  return (
    <div className="toggle-row">
      <Toggle
        on={sub}
        disabled={busy || state.status !== "ready" || (denied && !sub)}
        onChange={toggle}
      />
      <div className="toggle-row-text">
        <div className="toggle-row-title">Browser push — this device</div>
        <div className="toggle-row-sub">{note}</div>
        {error && (
          <div className="field-help field-error">{error}</div>
        )}
      </div>
      <span className="label">VIA VAPID</span>
    </div>
  );
}

// Database and image sizes, and whether the retention rule is on. The numbers
// cover the whole server, so every user sees the same ones.
export function StorageSection() {
  const [storage, setStorage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchStorage()
      .then((s) => { if (!cancelled) setStorage(s); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, []);

  const size = (key) => (storage ? formatBytes(storage[key]) : "…");
  const days = storage?.retention_unknown_days;

  return (
    <div className="settings-section">
      <h3>Storage</h3>
      <p className="lead">Images live in the database, so it grows with every capture. The backup dump grows with it.</p>
      {error && <div className="field-help field-error">Couldn't load storage sizes: {error}</div>}
      <Field label="Database" help="The whole database on disk.">
        <span className="tnum" style={{ fontSize: 20, fontWeight: 800 }}>{size("database_bytes")}</span>
      </Field>
      <Field label="Images" help="Full images and thumbnails, part of the database size.">
        <span className="tnum" style={{ fontSize: 20, fontWeight: 800 }}>{size("image_bytes")}</span>
      </Field>
      <Field label="Retention" help="Set by RETENTION_UNKNOWN_DAYS on the server.">
        <span>
          {storage == null ? "…"
            : days > 0 ? `Unknown sightings older than ${days} days are deleted daily.`
            : "Off. Nothing is deleted."}
        </span>
      </Field>
    </div>
  );
}

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
          <div className="label">Preferences</div>
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
                {acctErr.name && <div className="field-help field-error">{acctErr.name}</div>}
              </Field>
              <Field label="Email" help="Used for login and email notifications.">
                <input type="email" value={email} aria-label="Email"
                  aria-invalid={acctErr.email ? "true" : undefined}
                  onChange={e => setEmail(e.target.value)}
                  onBlur={() => commitField("email", email, me.email, checkEmail(email))} />
                {acctErr.email && <div className="field-help field-error">{acctErr.email}</div>}
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
                    <PushChannelRow />
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
                    <span className="tnum" style={{ fontSize: 20, fontWeight: 800 }}>{quiet}s</span>
                    <span className="label">10m</span>
                  </div>
                </div>
              </Field>

              <Field label="Notify only for new species"
                help="When on, you'll only be alerted the first time a species shows up.">
                <Toggle on={prefs.notify_new_species_only}
                  onChange={v => savePrefs({ notify_new_species_only: v })} />
              </Field>

              <Field label="Animal alerts"
                help="A push when Tier 2 names an animal at your feeder. Push only, never email. Separate from bird alerts, so a squirrel never mutes a bird.">
                <div className="animal-alerts" role="group" aria-label="Animal alerts">
                  {GROUPS.map(g => (
                    <div className="toggle-row" key={g.id}>
                      <Toggle on={!!prefs.animal_alerts?.[g.id]}
                        onChange={v => savePrefs({ animal_alerts: { [g.id]: v } })} />
                      <div className="toggle-row-text"><div className="toggle-row-title">{g.label}</div></div>
                    </div>
                  ))}
                </div>
              </Field>

              <Field label="Animal alert interval" help="At most one push per animal group per feeder this often.">
                <SelectInput label="Interval" value={String(prefs.animal_quiet_interval_seconds ?? 1800)}
                  onChange={v => savePrefs({ animal_quiet_interval_seconds: Number(v) })}
                  options={ANIMAL_INTERVALS.map(([s, l]) => [String(s), l])} />
              </Field>
            </div>
          )}

          {section === "appearance" && (
            <div className="settings-section">
              <h3>Appearance</h3>
              <p className="lead">Saved in this browser. A bird on screen sets the accent colour. The theme sets it everywhere else.</p>
              <Field label="Theme" help="Each theme has a light and a dark version.">
                <div className="theme-picker" role="group" aria-label="Theme">
                  {PALETTES.map(({ id, label }) => (
                    <button key={id} className={"theme-swatch" + (appearance.palette === id ? " active" : "")}
                      aria-pressed={appearance.palette === id}
                      onClick={() => updateAppearance({ palette: id })}>
                      <ThemePreview id={id} />
                      <span className="theme-swatch-label">{label}</span>
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Mode" help="Auto follows your device's light or dark setting.">
                <div className="segmented" role="group" aria-label="Mode">
                  {[["auto", "Auto"], ["day", "Light"], ["dusk", "Dark"]].map(([id, label]) => (
                    <button key={id} className={appearance.theme === id ? "active" : ""}
                      aria-pressed={appearance.theme === id}
                      onClick={() => updateAppearance({ theme: id })}>{label}</button>
                  ))}
                </div>
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

          {section === "storage" && <StorageSection />}
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

// A theme's light half and dark half side by side, each with its accent dot.
function ThemePreview({ id }) {
  return (
    <span className="theme-swatch-preview" aria-hidden="true">
      {["day", "dusk"].map((mode) => {
        const t = themeTokens(id, mode);
        return (
          <span key={mode} style={{ background: t["--bg"], color: t["--pal-acc"] }}>
            <i />
          </span>
        );
      })}
    </span>
  );
}
