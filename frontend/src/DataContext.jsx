// DataContext — loads all datasets from the backend once, after login, and
// exposes them to the pages. The app renders a global loading/error gate so
// pages can assume `data` is present.
//
// Phase 7 adds an offline path: the last successful set of payloads is kept in
// localStorage, so the app paints cached content immediately on open and keeps
// showing it (flagged `stale`) when a refresh can't reach the server. `error` is
// now only for the case where there is *nothing* to show.
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { fetchRaw, mapAll } from "./data.js";
import { clearSnapshot, loadSnapshot, saveSnapshot } from "./offline.js";

const Ctx = createContext(null);

// Read the snapshot once, synchronously, during the first render — waiting for
// an effect would flash the boot screen before the cached content appears.
function hydrate() {
  const snapshot = loadSnapshot();
  if (!snapshot) return null;
  try {
    return { data: mapAll(snapshot.raw), savedAt: snapshot.savedAt };
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
  // Whether anything is currently displayable. Tracked in a ref because
  // `reload` is memoized and would otherwise close over a stale `data`, and
  // because deciding inside a setState updater would run twice in strict mode.
  const hasData = useRef(initial != null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const raw = await fetchRaw();
      setData(mapAll(raw));
      hasData.current = true;
      setStale(null);
      saveSnapshot(raw);
    } catch (err) {
      if (err.isAuthError) {
        // The snapshot belongs to the session that just ended.
        clearSnapshot();
        hasData.current = false;
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
  }, [onAuthError]);

  useEffect(() => { reload(); }, [reload]);

  // Shallow-merge fields into the loaded dataset (e.g. after Settings saves the
  // current user), so dependent UI like the sidebar updates without a refetch.
  const patch = useCallback((partial) => {
    setData((d) => (d ? { ...d, ...partial } : d));
  }, []);

  return (
    <Ctx.Provider value={{ data, loading, error, stale, reload, patch }}>
      {children}
    </Ctx.Provider>
  );
}

export function useData() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
