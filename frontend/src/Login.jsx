// Login gate — minimal sign-in form that exchanges credentials for a JWT.
import React, { useState } from "react";
import { login } from "./api.js";

export function Login({ onSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-bg">
      <form className="login-card" onSubmit={submit}>
        <div className="brand" style={{ justifyContent: "center", marginBottom: 4 }}>
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M5 14 C 5 10 8 7 12 7 L 16 5 L 18 7 L 17 9 C 19 10 19 13 17 14 L 17 17 L 14 17 L 12 19 L 11 16 L 9 17 L 9 14 Z"
                fill="currentColor" />
              <circle cx="15" cy="9" r="0.7" fill="#1c2620" />
            </svg>
          </div>
        </div>
        <h1 className="display" style={{ fontSize: 30, textAlign: "center", margin: "6px 0 2px" }}>
          Peck Deck
        </h1>
        <div className="label" style={{ textAlign: "center", marginBottom: 22 }}>
          Field Station · Sign in
        </div>

        <label className="field-label" htmlFor="login-email">Email</label>
        <input id="login-email" type="email" value={email} autoFocus
          onChange={e => setEmail(e.target.value)} placeholder="dom@peck.deck" required
          style={{ width: "100%", marginBottom: 14 }} />

        <label className="field-label" htmlFor="login-pass">Password</label>
        <input id="login-pass" type="password" value={password}
          onChange={e => setPassword(e.target.value)} placeholder="••••••••" required
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
