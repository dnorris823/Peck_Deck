// Shell — sidebar nav, topbar, phone tab bar, brand mark
import React from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";

export const NAV = [
  { id: "dashboard", label: "Dashboard", short: "Home", icon: "home" },
  { id: "sightings", label: "Sightings", short: "Sightings", icon: "feather", countKey: "SIGHTINGS" },
  { id: "species", label: "Species Library", short: "Species", icon: "book", countKey: "SPECIES" },
  { id: "devices", label: "Stations", short: "Stations", icon: "device", countKey: "DEVICES" },
  { id: "users", label: "Users", icon: "users", countKey: "USERS" },
  { id: "settings", label: "Settings", icon: "gear" },
];

export function BrandMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M5 14 C 5 10 8 7 12 7 L 16 5 L 18 7 L 17 9 C 19 10 19 13 17 14 L 17 17 L 14 17 L 12 19 L 11 16 L 9 17 L 9 14 Z"
          fill="currentColor" />
        <circle cx="15" cy="9" r="0.7" fill="var(--paper)" />
      </svg>
    </div>
  );
}

function Brand() {
  return (
    <div className="brand">
      <BrandMark />
      <div>
        <div className="brand-name">Peck Deck</div>
        <div className="brand-sub">Field station</div>
      </div>
    </div>
  );
}

function NavItem({ n, route, setRoute, count }) {
  return (
    <button className={`nav-item ${route === n.id ? "active" : ""}`}
      aria-current={route === n.id ? "page" : undefined}
      onClick={() => setRoute(n.id)}>
      <Icon name={n.icon} />
      <span>{n.label}</span>
      {count != null && <span className="nav-count tnum">{count}</span>}
    </button>
  );
}

export function Sidebar({ route, setRoute, onLogout, open = false, onClose }) {
  const { data } = useData();
  const countFor = n => (n.countKey ? data[n.countKey].length : null);
  const me = data.ME;
  const initials = (me.name || "").trim().split(/\s+/).filter(Boolean)
    .slice(0, 2).map(p => p[0]).join("").toUpperCase() || "?";
  return (
    <aside className={`rail ${open ? "open" : ""}`} aria-label="Primary">
      <div className="rail-top">
        <Brand />
        <button className="icon-btn rail-close" aria-label="Close menu" onClick={onClose}>
          <Icon name="x" className="" />
        </button>
      </div>
      <nav className="nav">
        <div className="nav-section-label">Observatory</div>
        {NAV.slice(0, 4).map(n => (
          <NavItem key={n.id} n={n} route={route} setRoute={setRoute} count={countFor(n)} />
        ))}
        <div className="nav-section-label">Household</div>
        {NAV.slice(4).map(n => (
          <NavItem key={n.id} n={n} route={route} setRoute={setRoute} count={countFor(n)} />
        ))}
      </nav>
      <div className="rail-foot">
        <div className="avatar">{initials}</div>
        <div className="rail-foot-text">
          <div className="foot-name">{me.name}</div>
          <div className="foot-role">{me.role}</div>
        </div>
        <button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={onLogout}>
          <Icon name="logout" className="" />
        </button>
      </div>
    </aside>
  );
}

// Says whether GET /events is connected. It used to read "Live" whatever the
// stream was doing, which is the one thing a live indicator must not do.
export function LiveStatus() {
  const { live } = useData();
  return (
    <span className={`live-pill ${live ? "on" : ""}`} role="status"
      title={live ? "New visits appear as they happen" : "Not receiving live updates. Refresh to catch up."}>
      <span className={`live-dot ${live ? "on" : ""}`} aria-hidden="true" />
      {live ? "Live" : "Not live"}
    </span>
  );
}

export function Topbar({ route }) {
  const { reload, loading } = useData();
  const page = NAV.find(n => n.id === route);
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-brand"><BrandMark /></div>
        <div className="crumbs">{page?.label}</div>
      </div>
      <div className="top-actions">
        <LiveStatus />
        <button className="icon-btn" title="Refresh" aria-label="Refresh data"
          onClick={reload} disabled={loading}>
          <Icon name="refresh" className={loading ? "spin" : ""} />
        </button>
      </div>
    </header>
  );
}

// Phone navigation. The four pages people check from a phone sit one tap away;
// "More" opens the drawer for Users, Settings and sign out.
export function TabBar({ route, setRoute, onMore }) {
  const inMore = !NAV.slice(0, 4).some(n => n.id === route);
  return (
    <nav className="tabbar" aria-label="Primary">
      {NAV.slice(0, 4).map(n => (
        <button key={n.id} className={`tab ${route === n.id ? "active" : ""}`}
          aria-current={route === n.id ? "page" : undefined} onClick={() => setRoute(n.id)}>
          <Icon name={n.icon} className="tab-icon" />
          <span>{n.short}</span>
        </button>
      ))}
      <button className={`tab ${inMore ? "active" : ""}`} onClick={onMore}>
        <Icon name="more" className="tab-icon" />
        <span>More</span>
      </button>
    </nav>
  );
}
