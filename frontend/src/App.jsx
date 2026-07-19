// App — auth gate, data provider, top-level routing + simulated live alerts
import React, { useState, useEffect, useCallback } from "react";
import { Sidebar, Topbar, NAV } from "./Shell.jsx";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { Dashboard } from "./Dashboard.jsx";
import { Sightings, SightingDetail } from "./Sightings.jsx";
import { SpeciesPage } from "./Species.jsx";
import { DevicesPage } from "./Devices.jsx";
import { UsersPage, SettingsPage } from "./UsersSettings.jsx";
import { Login } from "./Login.jsx";
import { DataProvider, useData } from "./DataContext.jsx";
import { AppearanceProvider, useAppearance } from "./Appearance.jsx";
import { getToken, clearToken } from "./api.js";

export default function App() {
  return (
    <AppearanceProvider>
      <AppRoot />
    </AppearanceProvider>
  );
}

function AppRoot() {
  const [authed, setAuthed] = useState(() => !!getToken());
  const onAuthError = useCallback(() => setAuthed(false), []);

  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} />;
  }

  return (
    <DataProvider onAuthError={onAuthError}>
      <AppShell onLogout={() => { clearToken(); setAuthed(false); }} />
    </DataProvider>
  );
}

function AppShell({ onLogout }) {
  const { data, loading, error, reload } = useData();
  const { appearance } = useAppearance();
  const [route, setRoute] = useState("dashboard");
  const [openSighting, setOpenSighting] = useState(null);
  const [toast, setToast] = useState(null);
  const [navOpen, setNavOpen] = useState(false); // mobile off-canvas sidebar

  // Navigating always closes the mobile drawer.
  const go = useCallback((r) => { setRoute(r); setNavOpen(false); }, []);

  // Simulated live alert — a toast slides in shortly after each navigation.
  useEffect(() => {
    if (!appearance.showLiveAlerts || !data || data.SIGHTINGS.length === 0) return;
    const tid = window.setTimeout(() => {
      const fresh = data.SIGHTINGS[0];
      setToast({ ...fresh, key: Date.now() });
      window.setTimeout(() => setToast(null), 5400);
    }, 2200);
    return () => window.clearTimeout(tid);
  }, [route, data, appearance.showLiveAlerts]);

  if (loading && !data) {
    return <div className="boot"><div className="boot-mark">Loading field station…</div></div>;
  }
  if (error) {
    return (
      <div className="boot">
        <div className="boot-mark">Couldn't load data</div>
        <div className="boot-sub">{error}</div>
        <button className="btn primary sm" onClick={reload}>Retry</button>
      </div>
    );
  }

  return (
    <div className="app">
      {navOpen && <div className="nav-backdrop" onClick={() => setNavOpen(false)} aria-hidden="true" />}
      <Sidebar route={route} setRoute={go} onLogout={onLogout} open={navOpen} onClose={() => setNavOpen(false)} />
      <main className="main">
        <Topbar route={route} onOpenNav={() => setNavOpen(true)} />
        <div className="page" data-screen-label={NAV.find(n => n.id === route)?.label || route}>
          {route === "dashboard" && <Dashboard openSighting={setOpenSighting} />}
          {route === "sightings" && <Sightings openSighting={setOpenSighting} />}
          {route === "species" && <SpeciesPage />}
          {route === "devices" && <DevicesPage />}
          {route === "users" && <UsersPage />}
          {route === "settings" && <SettingsPage />}
        </div>
      </main>

      {openSighting && <SightingDetail s={openSighting} onClose={() => setOpenSighting(null)} />}

      {toast && (
        <div className="toast" key={toast.key} role="status" onClick={() => { setOpenSighting(toast); setToast(null); }}>
          <div className="toast-thumb"><BirdPlate species={toast.species} showLabel={false} /></div>
          <div>
            <div className="toast-name">{toast.species.common}</div>
            <div className="toast-sub">SPOTTED · {toast.device.name.toUpperCase()} · {Math.round(toast.confidence * 100)}% CONFIDENT</div>
          </div>
          <button className="icon-btn" aria-label="Dismiss alert" style={{ color: "var(--paper)" }} onClick={(e) => { e.stopPropagation(); setToast(null); }}>
            <Icon name="x" className="" />
          </button>
        </div>
      )}
    </div>
  );
}
