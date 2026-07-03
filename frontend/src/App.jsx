// App — top-level routing + simulated live notifications
import React, { useState, useEffect } from "react";
import { Sidebar, Topbar, NAV } from "./Shell.jsx";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { Dashboard } from "./Dashboard.jsx";
import { Sightings, SightingDetail } from "./Sightings.jsx";
import { SpeciesPage } from "./Species.jsx";
import { DevicesPage } from "./Devices.jsx";
import { UsersPage, SettingsPage } from "./UsersSettings.jsx";
import { SIGHTINGS } from "./data.js";

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

export default function App() {
  const [route, setRoute] = useState("dashboard");
  const [openSighting, setOpenSighting] = useState(null);
  const [toast, setToast] = useState(null);

  // Apply theme + accent + font as CSS variable overrides
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

  // Simulated live alert — a toast slides in shortly after each navigation.
  useEffect(() => {
    if (!APPEARANCE.showLiveAlerts) return;
    const tid = window.setTimeout(() => {
      const fresh = SIGHTINGS[0];
      setToast({ ...fresh, key: Date.now() });
      window.setTimeout(() => setToast(null), 5400);
    }, 2200);
    return () => window.clearTimeout(tid);
  }, [route]);

  return (
    <div className="app">
      <Sidebar route={route} setRoute={setRoute} />
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
