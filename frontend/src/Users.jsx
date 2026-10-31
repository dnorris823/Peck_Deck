// Users page. Owner only: the menu hides it from a viewer, and GET /users is 403.
import React, { useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, SelectInput, FormNote } from "./Modal.jsx";
import {
  createUser, updateUser, changePassword, setUserRole, signOutUser, deleteUser,
} from "./data.js";
import { useFeederAccess } from "./feederAccess.js";
import {
  checkRequired, checkEmail, checkPassword, collect, hasErrors,
} from "./validate.js";

// There is no email invite. The owner sets a temporary password and sends it.
const TEMP_PASSWORD_NOTE = "Set a temporary password and share it with them. They can change it in Settings.";

const ROLES = [["viewer", "Viewer"], ["owner", "Owner"]];

function InviteUserModal({ onClose, onDone }) {
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "viewer" });
  const [error, setError] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  function validate() {
    return collect({
      name: checkRequired(form.name, "Name"),
      email: checkEmail(form.email),
      password: checkPassword(form.password, { label: "Temporary password" }),
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
        role: form.role,
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
      subtitle={TEMP_PASSWORD_NOTE}
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
      <SelectInput label="Role" value={form.role} onChange={set("role")} options={ROLES} />
      <FormNote error={error} />
    </Modal>
  );
}

// Name, email, role and email alerts. The role has its own route, so a save
// that changes it makes two requests.
function UserDetailsForm({ user, onSaved }) {
  const [form, setForm] = useState({
    name: user.name, email: user.email, role: user.role, notify_email: user.notify_email,
  });
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);
  const set = k => v => { setForm(f => ({ ...f, [k]: v })); setNote(null); };

  async function save() {
    const errs = collect({
      name: checkRequired(form.name, "Name"),
      email: checkEmail(form.email),
    });
    setFieldErr(errs);
    if (hasErrors(errs)) { setError(null); return; }
    setBusy(true);
    setError(null);
    try {
      try {
        await updateUser(user.id, {
          name: form.name.trim(), email: form.email.trim(), notify_email: form.notify_email,
        });
      } catch (e) {
        throw e.status === 409 ? new Error("That email is already registered.") : e;
      }
      // A 409 here is the last owner, and the server's message says so.
      if (form.role !== user.role) await setUserRole(user.id, form.role);
      await onSaved();
      setNote("Saved.");
    } catch (e) {
      setError(e.message);
      await onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <TextInput label="Name" value={form.name} onChange={set("name")} error={fieldErr.name} />
      <TextInput label="Email" type="email" value={form.email} onChange={set("email")} error={fieldErr.email} />
      <SelectInput label="Role" value={form.role} onChange={set("role")} options={ROLES} />
      <label className="row" style={{ gap: 8, alignItems: "center" }}>
        <input type="checkbox" checked={form.notify_email} onChange={e => set("notify_email")(e.target.checked)} />
        <span>Email notifications</span>
      </label>
      <FormNote error={error} note={note} />
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save details"}</button>
      </div>
    </div>
  );
}

// One checkbox per feeder. Lists the feeders the signed-in owner sees, which
// are the ones they own or are a member of.
function UserFeeders({ user, devices, onChanged }) {
  const { access, loaded, error, share, unshare } = useFeederAccess(devices.map(d => d.id));
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function toggle(d, on) {
    setBusy(d.id);
    setActionError(null);
    try {
      if (on) await share(d.id, { user_id: user.id });
      else await unshare(d.id, user.id);
      await onChanged();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (error) return <div className="field-help field-error">Couldn't load feeders: {error}</div>;
  if (devices.length === 0) return <div className="field-help">No feeders yet.</div>;
  if (!loaded) return <div className="field-help">Loading…</div>;

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {devices.map(d => {
        const a = access.get(d.id);
        const owns = a?.owner.id === user.id;
        const member = !!a?.members.some(m => m.id === user.id);
        return (
          <label key={d.id} className="row" style={{ gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={owns || member} disabled={owns || busy != null}
              onChange={e => toggle(d, e.target.checked)} />
            <span>{d.name}</span>
            {owns && <span className="field-help">Owner</span>}
          </label>
        );
      })}
      <FormNote error={actionError} />
    </div>
  );
}

function ResetPassword({ user }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    const err = checkPassword(password, { label: "Temporary password" });
    if (err) { setError(err); return; }
    setBusy(true);
    setError(null);
    try {
      await changePassword(user.id, { new_password: password });
      setPassword("");
      setOpen(false);
      setNote(`Password reset. ${user.name} is signed out everywhere.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div style={{ display: "grid", gap: 6 }}>
        <div><button className="btn" onClick={() => { setOpen(true); setNote(null); }}>Reset password…</button></div>
        <FormNote note={note} />
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <TextInput label="Temporary password" type="password" value={password} onChange={setPassword}
        help={`${TEMP_PASSWORD_NOTE} Resetting signs them out on every device.`} />
      <FormNote error={error} />
      <div className="row" style={{ gap: 8 }}>
        <button className="btn" onClick={() => { setOpen(false); setError(null); }}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Resetting…" : "Reset password"}</button>
      </div>
    </div>
  );
}

function SignOutEverywhere({ user }) {
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await signOutUser(user.id);
      setNote(`${user.name} is signed out on every device. Their password still works.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div><button className="btn" onClick={submit} disabled={busy}>Sign out everywhere</button></div>
      <div className="field-help">For a lost phone. They sign in again with their password.</div>
      <FormNote error={error} note={note} />
    </div>
  );
}

function RemoveUser({ user, onRemoved }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await deleteUser(user.id);
      await onRemoved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {confirming ? (
        <>
          <div className="field-help">
            Remove {user.name}? Their account, feeder access and preferences are deleted.
            Remove them from the tailnet too.
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
            <button className="btn danger" onClick={submit} disabled={busy}>{busy ? "Removing…" : `Remove ${user.name}`}</button>
          </div>
        </>
      ) : (
        <div><button className="btn" onClick={() => setConfirming(true)}>Remove user…</button></div>
      )}
      <FormNote error={error} />
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ display: "grid", gap: 10, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
      <div className="label">{title}</div>
      {children}
    </div>
  );
}

function ManageUserModal({ user, me, devices, onClose, reload }) {
  const self = user.id === me.id;
  return (
    <Modal
      title={user.name}
      subtitle={user.email}
      onClose={onClose}
      maxWidth={560}
      footer={<button className="btn primary" onClick={onClose}>Done</button>}
    >
      <UserDetailsForm user={user} onSaved={reload} />
      <Section title="Feeders they see">
        {/* A change to your own access changes what this page loaded. */}
        <UserFeeders user={user} devices={devices} onChanged={self ? reload : async () => {}} />
      </Section>
      {self ? (
        <div className="field-help">Change your own password under Settings.</div>
      ) : (
        <Section title="Account">
          <ResetPassword user={user} />
          <SignOutEverywhere user={user} />
          <RemoveUser user={user} onRemoved={async () => { await reload(); onClose(); }} />
        </Section>
      )}
    </Modal>
  );
}

export function UsersPage() {
  const { data, reload } = useData();
  const { USERS, DEVICES, ME } = data;
  const [inviting, setInviting] = useState(false);
  const [managingId, setManagingId] = useState(null);
  // An id, so a save shows the reloaded row.
  const managing = USERS.find(u => u.id === managingId);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">People who watch your feeders</div>
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
              <div style={{ fontSize: 14, fontWeight: 500 }}>{u.name}{u.id === ME.id && " (you)"}</div>
              <div style={{ fontSize: 12.5, color: "var(--mu)", marginTop: 2 }}>
                {u.email}
              </div>
            </div>
            <span className={`role-badge role-${u.role}`}>{u.role}</span>
            <span className="label" style={{ fontSize: 10, display: "flex", gap: 10 }}>
              <span style={{ color: u.notify_email ? "var(--ok)" : "var(--mu)" }}>
                ✉ {u.notify_email ? "ON" : "OFF"}
              </span>
            </span>
            <button className="btn ghost sm" onClick={() => setManagingId(u.id)}>Manage</button>
          </div>
        ))}
      </div>

      {inviting && <InviteUserModal onClose={() => setInviting(false)} onDone={reload} />}
      {managing && (
        <ManageUserModal user={managing} me={ME} devices={DEVICES} reload={reload}
          onClose={() => setManagingId(null)} />
      )}
    </>
  );
}
