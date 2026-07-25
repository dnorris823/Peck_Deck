// Demo mode — reads GET /meta once and tells the app whether it is running as a
// public, read-only demo instance (FLEDGE Phase 5).
//
// Two surfaces come out of it: a banner across the shell, and the published
// credentials on the login card. The *enforcement* is entirely server-side (see
// backend/demo.py) — this is signage, not a control, so it can never be the
// thing standing between a visitor and a write.
import React, { createContext, useContext, useEffect, useState } from "react";
import { fetchMeta } from "./api.js";

const EMPTY = { demoMode: false, demoLogin: null };

const Ctx = createContext(EMPTY);

export function DemoProvider({ children }) {
  const [meta, setMeta] = useState(EMPTY);

  useEffect(() => {
    let cancelled = false;
    fetchMeta().then((m) => {
      if (cancelled || !m) return;
      setMeta({ demoMode: !!m.demo_mode, demoLogin: m.demo_login || null });
    });
    return () => { cancelled = true; };
  }, []);

  return <Ctx.Provider value={meta}>{children}</Ctx.Provider>;
}

export function useDemo() {
  return useContext(Ctx);
}

// Sticky strip at the top of the main column. Says both halves of the deal:
// the data is simulated, and nothing you change will stick.
export function DemoBanner() {
  const { demoMode } = useDemo();
  if (!demoMode) return null;
  return (
    <div className="demo-banner" role="status">
      <span className="demo-badge">Demo</span>
      <span className="demo-banner-text">
        Live data from a simulated feeder. This station is <strong>read-only</strong> —
        browse anything; edits won't be saved.
      </span>
    </div>
  );
}

// Login-card footnote. The credentials are published by the backend (only when
// DEMO_MODE is on), so a reviewer never has to be told them out of band.
export function DemoLoginHint({ onUse }) {
  const { demoMode, demoLogin } = useDemo();
  if (!demoMode || !demoLogin) return null;
  return (
    <div className="demo-hint">
      <div className="demo-hint-row">
        <span className="demo-badge">Demo</span>
        <span>Read-only station with a live simulated feed.</span>
      </div>
      <button type="button" className="btn ghost sm demo-hint-btn"
        onClick={() => onUse(demoLogin.email, demoLogin.password)}>
        Sign in as {demoLogin.email}
      </button>
    </div>
  );
}
