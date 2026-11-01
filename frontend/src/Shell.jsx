// Shell — top bar, phone tab bar, More menu, brand mark
import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { useDialog } from "./Modal.jsx";

// The five tabs sit in the top bar on desktop and in the tab bar on a phone.
// The rest live under More.
export const NAV = [
  { id: "latest", label: "Latest", icon: "home" },
  { id: "live", label: "Live", icon: "video" },
  { id: "species", label: "Species", icon: "book" },
  { id: "history", label: "History", icon: "feather" },
  { id: "feeders", label: "Feeders", icon: "device" },
  { id: "animals", label: "Animals", icon: "paw", more: true },
  { id: "users", label: "Users", icon: "users", more: true, owner: true },
  { id: "settings", label: "Settings", icon: "gear", more: true },
];

export const TABS = NAV.filter(n => !n.more);
const MORE = NAV.filter(n => n.more);

// Users is owner only. GET /users refuses a viewer.
export function moreFor(me) {
  return MORE.filter(n => !n.owner || me.role === "owner");
}

/** The route to show: `route`, unless `me` may not open it. */
export function allowedRoute(route, me) {
  const n = NAV.find(x => x.id === route);
  return n?.owner && me.role !== "owner" ? "latest" : route;
}

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

// The stream reports down on every page load until it connects, and on every
// drop until the first retry, which waits up to 3 s. A pill shown at once would
// flash through a normal reconnect, so it waits this long first.
export const LIVE_GRACE_MS = 5000;

// Shows only while GET /events is down. A green "Live" beside Home's "Offline"
// feeder pill read as a contradiction, and a connected stream needs no notice.
// The status region stays mounted, so a screen reader announces the change.
export function LiveStatus() {
  const { live } = useData();
  const [down, setDown] = useState(false);

  useEffect(() => {
    if (live) {
      setDown(false);
      return undefined;
    }
    const timer = setTimeout(() => setDown(true), LIVE_GRACE_MS);
    return () => clearTimeout(timer);
  }, [live]);

  return (
    <span className="live-status" role="status">
      {down && (
        <span className="live-pill" title="Not receiving live updates. Refresh to catch up.">
          <span className="live-dot" aria-hidden="true" />
          <span className="live-text">Reconnecting…</span>
        </span>
      )}
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

// Phone navigation: the five tabs, then More for Users, Settings and sign out.
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
        {moreFor(me).map(n => (
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
