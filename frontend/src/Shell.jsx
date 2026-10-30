// Shell — top bar, phone tab bar, More menu, brand mark
import React, { useRef } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { useDialog } from "./Modal.jsx";

// The four tabs sit in the top bar on desktop and in the tab bar on a phone.
// The rest live under More.
export const NAV = [
  { id: "latest", label: "Latest", icon: "home" },
  { id: "species", label: "Species", icon: "book" },
  { id: "history", label: "History", icon: "feather" },
  { id: "feeders", label: "Feeders", icon: "device" },
  { id: "users", label: "Users", icon: "users", more: true },
  { id: "settings", label: "Settings", icon: "gear", more: true },
];

export const TABS = NAV.filter(n => !n.more);
const MORE = NAV.filter(n => n.more);

// Screen ids before the "Latest bird" redesign. An installed app keeps the
// manifest shortcuts it was installed with, so the old ids must still land.
export const LEGACY_ROUTES = { dashboard: "latest", sightings: "history", devices: "feeders" };

export function BrandMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M5 14 C 5 10 8 7 12 7 L 16 5 L 18 7 L 17 9 C 19 10 19 13 17 14 L 17 17 L 14 17 L 12 19 L 11 16 L 9 17 L 9 14 Z"
          fill="currentColor" />
        <circle cx="15" cy="9" r="0.7" fill="var(--fg)" />
      </svg>
    </div>
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
      <span className="live-text">{live ? "Live" : "Not live"}</span>
    </span>
  );
}

export function TopBar({ route, setRoute, moreOpen, onMore }) {
  const { reload, loading } = useData();
  return (
    <header className="topbar">
      <div className="logo">Peck Deck</div>
      <nav className="tabs" aria-label="Primary">
        {TABS.map(n => (
          <button key={n.id} className={route === n.id ? "active" : ""}
            aria-current={route === n.id ? "page" : undefined} onClick={() => setRoute(n.id)}>
            {n.label}
          </button>
        ))}
      </nav>
      <div className="top-actions">
        <LiveStatus />
        <button className="icon-btn" title="Refresh" aria-label="Refresh data"
          onClick={reload} disabled={loading}>
          <Icon name="refresh" className={loading ? "spin" : ""} />
        </button>
        <button className="icon-btn more-btn" aria-label="More" aria-haspopup="menu"
          aria-expanded={moreOpen} onClick={onMore}>
          <Icon name="more" className="" />
        </button>
      </div>
    </header>
  );
}

// Phone navigation: the four tabs, then More for Users, Settings and sign out.
export function TabBar({ route, setRoute, moreOpen, onMore }) {
  const inMore = MORE.some(n => n.id === route);
  return (
    <nav className="tabbar" aria-label="Primary">
      {TABS.map(n => (
        <button key={n.id} className={`tab ${route === n.id ? "active" : ""}`}
          aria-current={route === n.id ? "page" : undefined} onClick={() => setRoute(n.id)}>
          <Icon name={n.icon} className="tab-icon" />
          <span>{n.label}</span>
        </button>
      ))}
      <button className={`tab ${inMore ? "active" : ""}`} aria-haspopup="menu"
        aria-expanded={moreOpen} onClick={onMore}>
        <Icon name="more" className="tab-icon" />
        <span>More</span>
      </button>
    </nav>
  );
}

// A dropdown under the top bar on desktop, a sheet above the tab bar on a phone.
export function MoreMenu({ route, setRoute, onLogout, onClose }) {
  const { data } = useData();
  const panelRef = useRef(null);
  useDialog(onClose, panelRef);
  const me = data.ME;
  const initials = (me.name || "").trim().split(/\s+/).filter(Boolean)
    .slice(0, 2).map(p => p[0]).join("").toUpperCase() || "?";
  return (
    <>
      <div className="more-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="more-menu" role="menu" aria-label="More" ref={panelRef} tabIndex={-1}>
        <div className="more-who">
          <div className="avatar">{initials}</div>
          <div className="more-who-text">
            <div className="foot-name">{me.name}</div>
            <div className="foot-role">{me.role}</div>
          </div>
        </div>
        {MORE.map(n => (
          <button key={n.id} role="menuitem" className={`more-item ${route === n.id ? "active" : ""}`}
            aria-current={route === n.id ? "page" : undefined} onClick={() => setRoute(n.id)}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </button>
        ))}
        <button role="menuitem" className="more-item" onClick={onLogout}>
          <Icon name="logout" />
          <span>Sign out</span>
        </button>
      </div>
    </>
  );
}
