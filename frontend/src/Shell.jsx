// Shell — sidebar nav + topbar + brand mark
import React from "react";
import { Icon } from "./Icon.jsx";
import { SIGHTINGS, SPECIES, DEVICES, USERS } from "./data.js";

export const NAV = [
  { id: "dashboard", label: "Dashboard", icon: "home" },
  { id: "sightings", label: "Sightings", icon: "feather", count: SIGHTINGS.length },
  { id: "species", label: "Species Library", icon: "book", count: SPECIES.length },
  { id: "devices", label: "Devices", icon: "device", count: DEVICES.length },
  { id: "users", label: "Users", icon: "users", count: USERS.length },
  { id: "settings", label: "Settings", icon: "gear" },
];

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        {/* Stylized bird-in-circle mark */}
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M5 14 C 5 10 8 7 12 7 L 16 5 L 18 7 L 17 9 C 19 10 19 13 17 14 L 17 17 L 14 17 L 12 19 L 11 16 L 9 17 L 9 14 Z"
            fill="currentColor" />
          <circle cx="15" cy="9" r="0.7" fill="#1c2620" />
        </svg>
      </div>
      <div>
        <div className="brand-name">Peck Deck</div>
        <div className="brand-sub">Field Station 01</div>
      </div>
    </div>
  );
}

export function Sidebar({ route, setRoute }) {
  return (
    <aside className="rail">
      <Brand />
      <nav className="nav">
        <div className="nav-section-label">Observatory</div>
        {NAV.slice(0, 4).map(n => (
          <button key={n.id} className={`nav-item ${route === n.id ? "active" : ""}`}
            onClick={() => setRoute(n.id)}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
            {n.count != null && <span className="nav-count tnum">{n.count}</span>}
          </button>
        ))}
        <div className="nav-section-label">Station</div>
        {NAV.slice(4).map(n => (
          <button key={n.id} className={`nav-item ${route === n.id ? "active" : ""}`}
            onClick={() => setRoute(n.id)}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
            {n.count != null && <span className="nav-count tnum">{n.count}</span>}
          </button>
        ))}
      </nav>
      <div className="rail-foot">
        <div className="avatar">DN</div>
        <div>
          <div className="foot-name">Dominic Norris</div>
          <div className="foot-role">OWNER · 3 DEVICES</div>
        </div>
      </div>
    </aside>
  );
}

export function Topbar({ route }) {
  const labels = {
    dashboard: ["Observatory", "Dashboard"],
    sightings: ["Observatory", "Sightings"],
    species: ["Observatory", "Species Library"],
    devices: ["Observatory", "Devices"],
    users: ["Station", "Users"],
    settings: ["Station", "Settings"],
  };
  const [a, b] = labels[route] || ["", ""];
  return (
    <header className="topbar">
      <div className="row" style={{ gap: 16 }}>
        <div className="crumbs">
          <span>{a}</span>
          <span className="crumb-sep">/</span>
          <span style={{ color: "var(--ink)" }}>{b}</span>
        </div>
        <span className="live-pill">
          <span className="live-dot" /> Live · 3 stations
        </span>
      </div>
      <div className="top-actions">
        <div className="search">
          <Icon name="search" className="" />
          <input placeholder="Search species, sightings…" />
          <span className="kbd">⌘K</span>
        </div>
        <button className="icon-btn" title="Notifications">
          <Icon name="bell" className="" />
        </button>
        <button className="btn primary sm">
          <Icon name="cam" className="" />
          New sighting
        </button>
      </div>
    </header>
  );
}
