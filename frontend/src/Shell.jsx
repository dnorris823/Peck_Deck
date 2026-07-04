// Shell — sidebar nav + topbar + brand mark
import React from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";

export const NAV = [
  { id: "dashboard", label: "Dashboard", icon: "home" },
  { id: "sightings", label: "Sightings", icon: "feather", countKey: "SIGHTINGS" },
  { id: "species", label: "Species Library", icon: "book", countKey: "SPECIES" },
  { id: "devices", label: "Devices", icon: "device", countKey: "DEVICES" },
  { id: "users", label: "Users", icon: "users", countKey: "USERS" },
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

function NavItem({ n, route, setRoute, count }) {
  return (
    <button className={`nav-item ${route === n.id ? "active" : ""}`}
      onClick={() => setRoute(n.id)}>
      <Icon name={n.icon} />
      <span>{n.label}</span>
      {count != null && <span className="nav-count tnum">{count}</span>}
    </button>
  );
}

export function Sidebar({ route, setRoute, onLogout }) {
  const { data } = useData();
  const countFor = n => (n.countKey ? data[n.countKey].length : null);
  const deviceCount = data.DEVICES.length;
  return (
    <aside className="rail">
      <Brand />
      <nav className="nav">
        <div className="nav-section-label">Observatory</div>
        {NAV.slice(0, 4).map(n => (
          <NavItem key={n.id} n={n} route={route} setRoute={setRoute} count={countFor(n)} />
        ))}
        <div className="nav-section-label">Station</div>
        {NAV.slice(4).map(n => (
          <NavItem key={n.id} n={n} route={route} setRoute={setRoute} count={countFor(n)} />
        ))}
      </nav>
      <div className="rail-foot">
        <div className="avatar">DN</div>
        <div style={{ flex: 1 }}>
          <div className="foot-name">Dominic Norris</div>
          <div className="foot-role">OWNER · {deviceCount} DEVICE{deviceCount === 1 ? "" : "S"}</div>
        </div>
        <button className="icon-btn" title="Sign out" onClick={onLogout}>
          <Icon name="x" className="" />
        </button>
      </div>
    </aside>
  );
}

export function Topbar({ route }) {
  const { data } = useData();
  const stations = data.DEVICES.length;
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
          <span className="live-dot" /> Live · {stations} station{stations === 1 ? "" : "s"}
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
