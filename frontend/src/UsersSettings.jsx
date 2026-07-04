// Users page + Settings page
import React, { useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { useAppearance } from "./Appearance.jsx";
import { saveMe, savePreferences } from "./data.js";

export function UsersPage() {
  const { USERS } = useData().data;
  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>People who watch your feeders</div>
          <h1 className="page-title">Users &amp; <em>roles</em></h1>
        </div>
        <button className="btn primary"><Icon name="plus" className="" /> Invite user</button>
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
            <button className="btn ghost sm">Edit</button>
          </div>
        ))}
      </div>
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

// A note for controls the backend can't persist yet.
function TodoNote({ children }) {
  return (
    <div className="field-help" style={{ marginTop: 8, opacity: 0.8, fontStyle: "italic" }}>
      TODO — {children}
    </div>
  );
}

const TIERS = [
  ["local", "Tier 1 — Local", "iNatVision TFLite on the Pi. Offline-friendly.", "PI ONLY"],
  ["gpu", "Tier 2 — LAN GPU", "Forwarded to RTX 5080. Higher accuracy.", "WIFI"],
  ["cloud", "Tier 3 — Cloud", "Anthropic Claude multimodal. Hard cases.", "INTERNET"],
  ["auto", "Auto", "Try local first. Escalate when confidence falls below threshold.", "RECOMMENDED"],
];

export function SettingsPage() {
  const { data, patch } = useData();
  const me = data.ME;
  const prefs = data.PREFERENCES;
  const { appearance, update: updateAppearance } = useAppearance();

  const [section, setSection] = useState("account");
  const [status, setStatus] = useState(null);

  // Account text fields buffer locally and persist on blur.
  const [name, setName] = useState(me.name);
  const [phone, setPhone] = useState(me.phone);

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
                <input type="text" value={name}
                  onChange={e => setName(e.target.value)}
                  onBlur={() => name !== me.name && saveUser({ name })} />
              </Field>
              <Field label="Email" help="Used for login and email notifications.">
                <input type="email" value={me.email} readOnly />
                <TodoNote>changing your email needs a new backend endpoint.</TodoNote>
              </Field>
              <Field label="Phone" help="E.164 format. Required for SMS.">
                <input type="text" value={phone}
                  onChange={e => setPhone(e.target.value)}
                  onBlur={() => phone !== me.phone && saveUser({ phone })} />
              </Field>
              <Field label="Password">
                <button className="btn" disabled>Change password…</button>
                <TodoNote>password changes need a POST /users/&#123;id&#125;/password route.</TodoNote>
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
    </>
  );
}
