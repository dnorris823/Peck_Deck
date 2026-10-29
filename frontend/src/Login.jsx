// Login gate — minimal sign-in form that exchanges credentials for a JWT.
import React, { useState } from "react";
import { login } from "./api.js";
import { checkEmail } from "./validate.js";
import { BrandMark } from "./Shell.jsx";

export function Login({ onSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function signIn(nextEmail, nextPassword) {
    setBusy(true);
    setError(null);
    try {
      await login(nextEmail, nextPassword);
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    const emailErr = checkEmail(email);
    if (emailErr) { setError(emailErr); return; }
    if (!password) { setError("Enter your password."); return; }
    await signIn(email.trim(), password);
  }

  return (
    <div className="login-bg">
      <form className="login-card" onSubmit={submit}>
        <div className="login-mark"><BrandMark /></div>
        <h1 className="login-title">Peck Deck</h1>
        <div className="login-sub">Sign in to see who's been at the feeder.</div>

        <label className="field-label" htmlFor="login-email">Email</label>
        <input id="login-email" type="email" value={email} autoFocus
          onChange={e => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="username" required
          style={{ width: "100%", marginBottom: 14 }} />

        <label className="field-label" htmlFor="login-pass">Password</label>
        <input id="login-pass" type="password" value={password}
          onChange={e => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" required
          style={{ width: "100%", marginBottom: 18 }} />

        {error && (
          <div className="login-error" role="alert">{error}</div>
        )}

        <button className="btn primary" type="submit" disabled={busy}
          style={{ width: "100%", justifyContent: "center" }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
