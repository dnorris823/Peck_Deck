// App — auth gate, data provider, top-level routing
import React, { useState, useCallback } from "react";
import { Sidebar, Topbar, NAV } from "./Shell.jsx";
import { Dashboard } from "./Dashboard.jsx";
import { Sightings, SightingDetail } from "./Sightings.jsx";
import { SpeciesPage } from "./Species.jsx";
import { DevicesPage } from "./Devices.jsx";
import { UsersPage, SettingsPage } from "./UsersSettings.jsx";
import { Login } from "./Login.jsx";
import { DataProvider, useData } from "./DataContext.jsx";
import { AppearanceProvider } from "./Appearance.jsx";
import { OfflineBanner, useOnline } from "./Offline.jsx";
import { getToken, clearToken } from "./api.js";

// Home-screen shortcuts in the web manifest deep-link with ?screen=<id>, so a
// long-press on the installed icon can open straight to Sightings or Species.
function initialRoute() {
  const wanted = new URLSearchParams(window.location.search).get("screen");
  return NAV.some((n) => n.id === wanted) ? wanted : "dashboard";
}

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
      <AppShell onLogout={() => {
        clearToken();
        setAuthed(false);
      }} />
    </DataProvider>
  );
}

function AppShell({ onLogout }) {
  const { data, loading, error, reload } = useData();
  const online = useOnline();
  const [route, setRoute] = useState(initialRoute);
  const [openSighting, setOpenSighting] = useState(null);
  const [navOpen, setNavOpen] = useState(false); // mobile off-canvas sidebar

  // Navigating always closes the mobile drawer.
  const go = useCallback((r) => { setRoute(r); setNavOpen(false); }, []);

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
        {/* Banner and topbar stick as one block, so the banner wrapping to two
            lines on a phone can't slide it under the topbar. */}
        <div className="topstack">
          <OfflineBanner offline={!online} loading={loading} onRetry={reload} />
          <Topbar route={route} onOpenNav={() => setNavOpen(true)} />
        </div>
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

    </div>
  );
}
