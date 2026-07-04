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
import { getToken, clearToken } from "./api.js";

// Appearance defaults carried over from the Claude Design prototype's Tweaks
// panel. The panel itself was a design-canvas tool (it drives the editor over
// postMessage) and is intentionally not shipped; these values are applied
// directly so theming still works. Wire these to Settings > Appearance later.
const APPEARANCE = {
  theme: "day",
  accent: "cardinal",
  displayFont: "newsreader",
  showLiveAlerts: true,
  fontScale: 1,
};

function useAppearance() {
  useEffect(() => {
    const t = APPEARANCE;
    document.documentElement.dataset.theme = t.theme;
    const accents = {
      cardinal: { primary: "#b8412c", deep: "#8a2f1e" },
      forest: { primary: "#2d4a36", deep: "#1d3225" },
      yolk: { primary: "#d4a23a", deep: "#a37a1f" },
      plum: { primary: "#6b4570", deep: "#4a2f51" },
    };
    const a = accents[t.accent] || accents.cardinal;
    document.documentElement.style.setProperty("--cardinal", a.primary);
    document.documentElement.style.setProperty("--cardinal-deep", a.deep);

    const fonts = {
      newsreader: '"Newsreader", "Times New Roman", serif',
      instrument: '"Instrument Serif", "Times New Roman", serif',
      playfair: '"Playfair Display", "Times New Roman", serif',
      eb: '"EB Garamond", "Times New Roman", serif',
    };
    document.documentElement.style.setProperty("--display", fonts[t.displayFont] || fonts.newsreader);
    document.documentElement.style.fontSize = `${14 * t.fontScale}px`;
  }, []);
}

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken());
  useAppearance();

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
  const [route, setRoute] = useState("dashboard");
  const [openSighting, setOpenSighting] = useState(null);
  const [toast, setToast] = useState(null);

  // Simulated live alert — a toast slides in shortly after each navigation.
  useEffect(() => {
    if (!APPEARANCE.showLiveAlerts || !data || data.SIGHTINGS.length === 0) return;
    const tid = window.setTimeout(() => {
      const fresh = data.SIGHTINGS[0];
      setToast({ ...fresh, key: Date.now() });
      window.setTimeout(() => setToast(null), 5400);
    }, 2200);
    return () => window.clearTimeout(tid);
  }, [route, data]);

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
      <Sidebar route={route} setRoute={setRoute} onLogout={onLogout} />
      <main className="main">
        <Topbar route={route} />
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
        <div className="toast" key={toast.key} onClick={() => { setOpenSighting(toast); setToast(null); }}>
          <div className="toast-thumb"><BirdPlate species={toast.species} showLabel={false} /></div>
          <div>
            <div className="toast-name">{toast.species.common}</div>
            <div className="toast-sub">SPOTTED · {toast.device.name.toUpperCase()} · {Math.round(toast.confidence * 100)}% CONFIDENT</div>
          </div>
          <button className="icon-btn" style={{ color: "var(--paper)" }} onClick={(e) => { e.stopPropagation(); setToast(null); }}>
            <Icon name="x" className="" />
          </button>
        </div>
      )}
    </div>
  );
}
