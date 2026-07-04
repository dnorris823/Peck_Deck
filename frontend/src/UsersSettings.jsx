// Users page + Settings page
import React, { useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";

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

export function SettingsPage() {
  const [section, setSection] = useState("notifications");
  const [emailOn, setEmailOn] = useState(true);
  const [smsOn, setSmsOn] = useState(true);
  const [quietInterval, setQuietInterval] = useState(60);
  const [tier, setTier] = useState("auto");
  const [confThresh, setConfThresh] = useState(70);

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
              <h3>Account details</h3>
              <p className="lead">How you appear to other users and how the app reaches you.</p>
              <Field label="Name">
                <input type="text" defaultValue="Dominic Norris" />
              </Field>
              <Field label="Email" help="Used for login and email notifications.">
                <input type="email" defaultValue="dom@peck.deck" />
              </Field>
              <Field label="Phone" help="E.164 format. Required for SMS.">
                <input type="text" defaultValue="+18025550142" />
              </Field>
              <Field label="Password">
                <button className="btn">Change password…</button>
              </Field>
            </div>
          )}

          {section === "notifications" && (
            <div className="settings-section">
              <h3>Notifications</h3>
              <p className="lead">When a bird is identified, who gets notified, and how often.</p>

              <Field label="Channels" help="You can toggle each independently — at least one must be on to receive alerts.">
                <div className="card">
                  <div className="card-pad" style={{ padding: "4px 16px" }}>
                    <div className="toggle-row">
                      <Toggle on={emailOn} onChange={setEmailOn} />
                      <div className="toggle-row-text">
                        <div className="toggle-row-title">Email — dom@peck.deck</div>
                        <div className="toggle-row-sub">Inline thumbnail + species card + Wikipedia link</div>
                      </div>
                      <span className="label">VIA SENDGRID</span>
                    </div>
                    <div className="toggle-row">
                      <Toggle on={smsOn} onChange={setSmsOn} />
                      <div className="toggle-row-text">
                        <div className="toggle-row-title">SMS — +1 (802) 555-0142</div>
                        <div className="toggle-row-sub">Concise text + MMS image where supported</div>
                      </div>
                      <span className="label">VIA TWILIO</span>
                    </div>
                  </div>
                </div>
              </Field>

              <Field label="Quiet interval" help="Minimum seconds between notifications per device. Prevents spam during a long visit.">
                <div>
                  <input type="range" min="10" max="600" step="10" value={quietInterval}
                    onChange={e => setQuietInterval(Number(e.target.value))}
                    style={{ width: "100%" }} />
                  <div className="between" style={{ marginTop: 6 }}>
                    <span className="label">10s</span>
                    <span className="display-i tnum" style={{ fontSize: 22 }}>{quietInterval}s</span>
                    <span className="label">10m</span>
                  </div>
                </div>
              </Field>

              <Field label="Notify only for new species"
                help="When on, you'll only be alerted the first time a species shows up.">
                <Toggle on={false} onChange={() => {}} />
              </Field>
            </div>
          )}

          {section === "classification" && (
            <div className="settings-section">
              <h3>Classification</h3>
              <p className="lead">Default tier for new stations. Per-station overrides live in Devices.</p>

              <Field label="Default tier">
                <div className="tier-stack">
                  {[
                    ["local", "Tier 1 — Local", "iNatVision TFLite on the Pi. Offline-friendly.", "PI ONLY"],
                    ["gpu", "Tier 2 — LAN GPU", "Forwarded to RTX 5080. Higher accuracy.", "WIFI"],
                    ["cloud", "Tier 3 — Cloud", "Anthropic Claude multimodal. Hard cases.", "INTERNET"],
                    ["auto", "Auto", "Try local first. Escalate when confidence falls below threshold.", "RECOMMENDED"],
                  ].map(([k, n, d, b], i) => (
                    <div key={k} className={`tier-card ${tier === k ? "selected" : ""}`} onClick={() => setTier(k)}>
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
                  <input type="range" min="40" max="95" step="1" value={confThresh}
                    onChange={e => setConfThresh(Number(e.target.value))}
                    style={{ width: "100%" }} />
                  <div className="between" style={{ marginTop: 6 }}>
                    <span className="label">40%</span>
                    <span className="display-i tnum" style={{ fontSize: 22 }}>{confThresh}%</span>
                    <span className="label">95%</span>
                  </div>
                </div>
              </Field>

              <Field label="Debounce window"
                help="Skip duplicate captures within this window of a confirmed sighting.">
                <select defaultValue="30">
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
              <p className="lead">Stored as environment variables on the gaming PC. Never sent to the Pi.</p>
              <Field label="Anthropic Claude" help="Powers Tier 3 cloud classification.">
                <input type="password" defaultValue="sk-ant-•••••••••••••••••0a9b" />
                <button className="btn sm" style={{ alignSelf: "flex-start", marginTop: 6 }}>Test connection</button>
              </Field>
              <Field label="SendGrid" help="Outbound transactional email.">
                <input type="password" defaultValue="SG.•••••••••••••••••8f2c" />
              </Field>
              <Field label="Twilio" help="SMS + MMS for mobile alerts.">
                <input type="text" placeholder="Account SID" defaultValue="AC1234567890abcdef" />
                <input type="password" placeholder="Auth Token" defaultValue="••••••••••••••••" style={{ marginTop: 6 }} />
              </Field>
            </div>
          )}

          {section === "appearance" && (
            <div className="settings-section">
              <h3>Appearance</h3>
              <p className="lead">Visual preferences for the field journal interface.</p>
              <Field label="Theme">
                <div className="row">
                  <button className="btn">Day</button>
                  <button className="btn">Dusk</button>
                </div>
              </Field>
              <Field label="Density">
                <select defaultValue="comfortable">
                  <option>Compact</option>
                  <option>Comfortable</option>
                  <option>Spacious</option>
                </select>
              </Field>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
