// App — auth gate, data provider, top-level routing
import React, { useState, useCallback, useEffect, useRef } from "react";
import { TopBar, TabBar, MoreMenu, NAV, LEGACY_ROUTES } from "./Shell.jsx";
import { Dashboard } from "./Dashboard.jsx";
import { Sightings } from "./Sightings.jsx";
import { SightingDetail } from "./SightingDetail.jsx";
import { SpeciesPage } from "./Species.jsx";
import { DevicesPage } from "./Devices.jsx";
import { UsersPage, SettingsPage } from "./UsersSettings.jsx";
import { Login } from "./Login.jsx";
import { DataProvider, useData } from "./DataContext.jsx";
import { AppearanceProvider } from "./Appearance.jsx";
import { OfflineBanner, useOnline } from "./Offline.jsx";
import { getToken, clearToken } from "./api.js";
import { useSpeciesAccent } from "./accent.js";
import { fetchSighting, mapAgainst } from "./data.js";

// Home-screen shortcuts in the web manifest deep-link with ?screen=<id>, so a
// long-press on the installed icon can open straight to History or Species.
export function initialRoute(search = window.location.search) {
  const asked = new URLSearchParams(search).get("screen");
  const wanted = LEGACY_ROUTES[asked] || asked;
  return NAV.some((n) => n.id === wanted) ? wanted : "latest";
}

// Each sighting has its own URL, ?sighting=<id>, so a push notification opens it
// directly. Null when the URL names none.
export function sightingFromUrl(search = window.location.search) {
  const id = Number(new URLSearchParams(search).get("sighting"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** The current URL with ?sighting= set to `id`, or removed for null. */
export function urlWithSighting(id, location = window.location) {
  const params = new URLSearchParams(location.search);
  if (id == null) params.delete("sighting");
  else params.set("sighting", String(id));
  const query = params.toString();
  return `${location.pathname}${query ? `?${query}` : ""}${location.hash}`;
}

/**
 * Which sighting is open, kept in step with the URL.
 *
 * Opening from a screen pushes a history entry, so the phone's back gesture
 * closes the view. Moving along the strip, or opening a second sighting while
 * the desktop panel shows one, replaces it, so Back doesn't walk every visit.
 * A URL the app booted with, from a push notification, has no entry of ours
 * behind it, so closing that one rewrites the URL instead of going back.
 */
function useOpenSighting() {
  const [openId, setOpenId] = useState(sightingFromUrl);
  const openRef = useRef(openId);
  openRef.current = openId;

  useEffect(() => {
    const onPop = () => setOpenId(sightingFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const show = useCallback((sighting) => {
    const state = { ...(window.history.state || {}), sighting: sighting.id };
    if (openRef.current == null) {
      window.history.pushState({ ...state, pushed: true }, "", urlWithSighting(sighting.id));
    } else {
      window.history.replaceState(state, "", urlWithSighting(sighting.id));
    }
    openRef.current = sighting.id;
    setOpenId(sighting.id);
  }, []);

  const close = useCallback(() => {
    if (openRef.current == null) return;
    const pushed = window.history.state?.pushed;
    // Cleared now, not on popstate, so a second close in the same tick (delete,
    // then the sighting vanishing from the list) can't go back twice.
    openRef.current = null;
    setOpenId(null);
    if (pushed) window.history.back();
    else window.history.replaceState(null, "", urlWithSighting(null));
  }, []);

  return { openId, show, close };
}

/**
 * The open sighting as an object. From the loaded list when it is there, else
 * fetched by id, for a push about a visit older than the loaded window. Both
 * go through mapSighting in data.js, the same as streamed ones.
 *
 * Also returns a setter for the row a species correction sends back. A loaded
 * sighting updates through DataContext, but a fetched one is held only here.
 * The row is mapped at render, against data that by then holds its species.
 */
function useSightingById(id, data, onMissing) {
  const loaded = id == null ? null : data?.SIGHTINGS.find((s) => s.id === id) || null;
  const [fetched, setFetched] = useState(null);
  const [corrected, setCorrected] = useState(null);

  useEffect(() => {
    if (id == null || loaded || !data || fetched?.id === id) return;
    let cancelled = false;
    fetchSighting(id, data)
      .then((s) => {
        if (cancelled) return;
        if (s) setFetched(s);
        else onMissing();
      })
      // Deleted, never existed, or unreachable: nothing to show.
      .catch(() => { if (!cancelled) onMissing(); });
    return () => { cancelled = true; };
  }, [id, loaded, data, fetched, onMissing]);

  if (loaded) return [loaded, setCorrected];
  if (fetched?.id !== id) return [null, setCorrected];
  const remapped = corrected?.id === id ? mapAgainst(corrected, data) : null;
  return [remapped || fetched, setCorrected];
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
  const { openId, show: openSighting, close: closeSighting } = useOpenSighting();
  const [sighting, onCorrected] = useSightingById(openId, data, closeSighting);
  const [moreOpen, setMoreOpen] = useState(false);
  // Species filter handed to Sightings, so "View sightings" on a species lands
  // on that species' visits rather than the whole list.
  const [speciesFilter, setSpeciesFilter] = useState("all");

  // Navigating always closes the More menu and the sighting, and starts at
  // the top.
  const go = useCallback((r, { species = "all" } = {}) => {
    setRoute(r);
    setSpeciesFilter(species);
    setMoreOpen(false);
    closeSighting();
    window.scrollTo?.(0, 0);
  }, [closeSighting]);
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
      <div className="app-body">
        <main className="main">
          <div className="page" data-screen-label={NAV.find(n => n.id === route)?.label || route}>
            {route === "latest" && <Dashboard openSighting={openSighting} go={go} selectedId={openId} />}
            {route === "history" && (
              <Sightings key={speciesFilter} openSighting={openSighting} initialSpecies={speciesFilter} />
            )}
            {route === "species" && <SpeciesPage go={go} openSighting={openSighting} />}
            {route === "feeders" && <DevicesPage />}
            {route === "users" && <UsersPage />}
            {route === "settings" && <SettingsPage />}
          </div>
        </main>
        {/* Beside the page on desktop, over it on a phone. sighting-detail.css. */}
        {sighting && (
          <SightingDetail s={sighting} onClose={closeSighting} onMove={openSighting}
            onCorrected={onCorrected} backLabel={NAV.find(n => n.id === route)?.label} />
        )}
      </div>
      <TabBar route={route} setRoute={go} moreOpen={moreOpen} onMore={toggleMore} />
      {moreOpen && <MoreMenu route={route} setRoute={go} onLogout={onLogout} onClose={closeMore} />}
    </div>
  );
}
