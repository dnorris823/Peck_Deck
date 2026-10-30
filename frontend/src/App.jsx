// App — auth gate, data provider, top-level routing
import React, { useState, useCallback } from "react";
import { TopBar, TabBar, MoreMenu, NAV, LEGACY_ROUTES } from "./Shell.jsx";
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
import { useSpeciesAccent } from "./accent.js";

// Home-screen shortcuts in the web manifest deep-link with ?screen=<id>, so a
// long-press on the installed icon can open straight to History or Species.
export function initialRoute(search = window.location.search) {
  const asked = new URLSearchParams(search).get("screen");
  const wanted = LEGACY_ROUTES[asked] || asked;
  return NAV.some((n) => n.id === wanted) ? wanted : "latest";
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
  const [moreOpen, setMoreOpen] = useState(false);
  // Species filter handed to Sightings, so "View sightings" on a species lands
  // on that species' visits rather than the whole list.
  const [speciesFilter, setSpeciesFilter] = useState("all");

  // Navigating always closes the More menu and starts at the top.
  const go = useCallback((r, { species = "all" } = {}) => {
    setRoute(r);
    setSpeciesFilter(species);
    setMoreOpen(false);
    window.scrollTo?.(0, 0);
  }, []);
  const closeMore = useCallback(() => setMoreOpen(false), []);
  const toggleMore = useCallback(() => setMoreOpen(o => !o), []);

  // The app-wide accent is the latest visitor's. A screen that shows another
  // bird sets its own accent on that part of the page.
  const accent = useSpeciesAccent(data?.SIGHTINGS[0]?.species);

  if (loading && !data) {
    return <div className="boot"><div className="boot-mark">Loading Peck Deck…</div></div>;
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
    <div className="app" style={accent}>
      <div className="topstack">
        {/* Banner and top bar stick as one block, so the banner wrapping to two
            lines on a phone can't slide it under the bar. */}
        <OfflineBanner offline={!online} loading={loading} onRetry={reload} />
        <TopBar route={route} setRoute={go} moreOpen={moreOpen} onMore={toggleMore} />
      </div>
      <main className="main">
        <div className="page" data-screen-label={NAV.find(n => n.id === route)?.label || route}>
          {route === "latest" && <Dashboard openSighting={setOpenSighting} go={go} />}
          {route === "history" && (
            <Sightings key={speciesFilter} openSighting={setOpenSighting} initialSpecies={speciesFilter} />
          )}
          {route === "species" && <SpeciesPage go={go} />}
          {route === "feeders" && <DevicesPage />}
          {route === "users" && <UsersPage />}
          {route === "settings" && <SettingsPage />}
        </div>
      </main>
      <TabBar route={route} setRoute={go} moreOpen={moreOpen} onMore={toggleMore} />
      {moreOpen && <MoreMenu route={route} setRoute={go} onLogout={onLogout} onClose={closeMore} />}

      {openSighting && <SightingDetail s={openSighting} onClose={() => setOpenSighting(null)} />}
    </div>
  );
}
