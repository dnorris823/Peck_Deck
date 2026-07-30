// DataContext — loads all datasets from the backend once, after login, and
// exposes them to the pages. The app renders a global loading/error gate so
// pages can assume `data` is present.
//
// Phase 7 adds an offline path: the last successful set of payloads is kept in
// localStorage, so the app paints cached content immediately on open and keeps
// showing it (flagged `stale`) when a refresh can't reach the server. `error` is
// now only for the case where there is *nothing* to show.
//
// It then held that first load forever — no polling, no push — so a running
// feeder changed nothing on screen until someone reloaded the page. A live
// stream (GET /events) now applies new sightings as they happen: the event
// carries the sighting row, so the feed costs no refetch and only the derived
// aggregates are re-read. See frontend/src/events.js.
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { applySighting, fetchAggregates, fetchRaw, mapAll } from "./data.js";
import { openSightingStream } from "./events.js";
import { clearSnapshot, loadSnapshot, saveSnapshot } from "./offline.js";

const Ctx = createContext(null);

// Read the snapshot once, synchronously, during the first render — waiting for
// an effect would flash the boot screen before the cached content appears.
function hydrate() {
  const snapshot = loadSnapshot();
  if (!snapshot) return null;
  try {
    return { data: mapAll(snapshot.raw), raw: snapshot.raw, savedAt: snapshot.savedAt };
  } catch {
    // A payload the current mapper can't read is worse than none.
    clearSnapshot();
    return null;
  }
}

export function DataProvider({ children, onAuthError }) {
  const [initial] = useState(hydrate);
  const [data, setData] = useState(initial?.data ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Set when what's on screen came from the snapshot rather than this session's
  // network call: either the first paint before the refresh lands, or a refresh
  // that failed while cached data was already up.
  const [stale, setStale] = useState(initial ? { savedAt: initial.savedAt } : null);
  // Whether the event stream is currently connected. Purely informational — the
  // app is fully usable without it, it just stops updating on its own.
  const [live, setLive] = useState(false);
  // Whether anything is currently displayable. Tracked in a ref because
  // `reload` is memoized and would otherwise close over a stale `data`, and
  // because deciding inside a setState updater would run twice in strict mode.
  const hasData = useRef(initial != null);
  // The last raw payloads. Kept because a streamed sighting patches the raw
  // set and re-maps it — mapping is not reversible, so the mapped `data` alone
  // is not enough to build the next one from.
  const rawRef = useRef(initial?.raw ?? null);
  // Mapped fields written by `patch` (e.g. the current user after Settings
  // saves). They have to survive a re-map: before the stream existed, `patch`
  // was the last word until the next reload, but a streamed sighting now
  // re-maps the whole dataset and would otherwise revert them mid-session.
  const overridesRef = useRef({});

  const commit = useCallback((raw) => {
    rawRef.current = raw;
    setData({ ...mapAll(raw), ...overridesRef.current });
    hasData.current = true;
    setStale(null);
    saveSnapshot(raw);
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const raw = await fetchRaw();
      // A full load is fresh server truth, and every patched field was written
      // to the server before it was patched here — so the overrides are now at
      // best redundant and at worst masking someone else's change.
      overridesRef.current = {};
      commit(raw);
    } catch (err) {
      if (err.isAuthError) {
        // The snapshot belongs to the session that just ended.
        clearSnapshot();
        hasData.current = false;
        rawRef.current = null;
        setData(null);
        onAuthError?.();
      } else if (hasData.current) {
        // Cached content beats an error page; the banner says it isn't live.
        setStale((s) => s ?? { savedAt: Date.now() });
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [commit, onAuthError]);

  useEffect(() => { reload(); }, [reload]);

  // Apply one streamed sighting: prepend the row we were handed, then refetch
  // only what it invalidated.
  const applyStreamed = useCallback(async (sighting) => {
    const raw = rawRef.current;
    // Nothing loaded yet — the reload in flight will include this sighting
    // anyway, so there is nothing to patch onto.
    if (!raw) return;

    const sightings = applySighting(raw.sightings, sighting);
    if (sightings === raw.sightings) return; // already had it (replay overlap)

    // Paint the new visit immediately, then let the aggregates catch up. Waiting
    // for the refetch would put a network round trip between the bird arriving
    // and the feed showing it, which is the latency this whole change removes.
    commit({ ...raw, sightings });

    try {
      const known = raw.species.some((s) => s.id === sighting.species_id);
      const patch = await fetchAggregates({ withSpecies: !known });
      commit({ ...rawRef.current, ...patch });
    } catch {
      // The feed is already correct; the aggregates are merely a few visits
      // behind and the next event or manual refresh fixes them.
    }
  }, [commit]);

  useEffect(() => {
    const stop = openSightingStream({
      onSighting: applyStreamed,
      onResync: reload,
      onStatus: setLive,
      onAuthError: () => {
        clearSnapshot();
        hasData.current = false;
        rawRef.current = null;
        setData(null);
        onAuthError?.();
      },
    });
    return stop;
  }, [applyStreamed, reload, onAuthError]);

  // Shallow-merge fields into the loaded dataset (e.g. after Settings saves the
  // current user), so dependent UI like the sidebar updates without a refetch.
  const patch = useCallback((partial) => {
    overridesRef.current = { ...overridesRef.current, ...partial };
    setData((d) => (d ? { ...d, ...partial } : d));
  }, []);

  return (
    <Ctx.Provider value={{ data, loading, error, stale, live, reload, patch }}>
      {children}
    </Ctx.Provider>
  );
}

export function useData() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
