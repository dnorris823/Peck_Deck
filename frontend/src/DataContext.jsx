// DataContext — loads all datasets from the backend once, after login, and
// exposes them to the pages. The app renders a global loading/error gate so
// pages can assume `data` is present.
//
// A live stream (GET /events) then applies new sightings as they happen: the
// event carries the sighting row, so the feed costs no refetch and only the
// derived aggregates are re-read. See frontend/src/events.js.
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import {
  applySighting, fetchAggregates, fetchRaw, forgetSpeciesHours, mapAll, removeSighting,
  replaceSighting,
} from "./data.js";
import { openSightingStream } from "./events.js";

const Ctx = createContext(null);

export function DataProvider({ children, onAuthError }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Whether the event stream is currently connected. Purely informational — the
  // app is fully usable without it, it just stops updating on its own.
  const [live, setLive] = useState(false);
  // Whether anything is currently displayable. Tracked in a ref because
  // `reload` is memoized and would otherwise close over a stale `data`, and
  // because deciding inside a setState updater would run twice in strict mode.
  const hasData = useRef(false);
  // The last raw payloads. Kept because a streamed sighting patches the raw
  // set and re-maps it — mapping is not reversible, so the mapped `data` alone
  // is not enough to build the next one from.
  const rawRef = useRef(null);
  // Mapped fields written by `patch` (e.g. the current user after Settings
  // saves). They have to survive a re-map: before the stream existed, `patch`
  // was the last word until the next reload, but a streamed sighting now
  // re-maps the whole dataset and would otherwise revert them mid-session.
  const overridesRef = useRef({});
  // Versions of updated sightings already applied, as "id@corrected_at". The
  // tab that made a change applies it itself, then hears it again on the stream.
  const appliedRef = useRef(new Set());

  const commit = useCallback((raw) => {
    rawRef.current = raw;
    setData({ ...mapAll(raw), ...overridesRef.current });
    hasData.current = true;
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
        hasData.current = false;
        rawRef.current = null;
        setData(null);
        onAuthError?.();
      } else if (!hasData.current) {
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

  // Drop a deleted sighting. The tab that deleted it calls this itself, so it
  // updates with the stream down. Every other tab gets it from the stream.
  const applyDeleted = useCallback(async (id) => {
    const raw = rawRef.current;
    if (!raw) return;

    const sightings = removeSighting(raw.sightings, id);
    if (sightings === raw.sightings) return; // not held, or already dropped

    commit({ ...raw, sightings });

    try {
      commit({ ...rawRef.current, ...(await fetchAggregates()) });
    } catch {
      // As for a new sighting: the feed is right, the counts catch up later.
    }
  }, [commit]);

  // Swap in an updated sighting, such as a corrected species. Applied whether
  // or not the row is in the loaded window, because the counts move either way.
  const applyUpdated = useCallback(async (sighting) => {
    const raw = rawRef.current;
    if (!raw) return;
    const version = `${sighting.id}@${sighting.corrected_at}`;
    if (appliedRef.current.has(version)) return;
    appliedRef.current.add(version);
    forgetSpeciesHours();

    const known = raw.species.some((s) => s.id === sighting.species_id);
    try {
      if (known) {
        commit({ ...raw, sightings: replaceSighting(raw.sightings, sighting) });
        commit({ ...rawRef.current, ...(await fetchAggregates()) });
      } else {
        // mapAll drops a sighting it can't join to a species, which would also
        // close it in the detail view. So the species list comes first.
        const patch = await fetchAggregates({ withSpecies: true });
        const now = rawRef.current;
        commit({ ...now, ...patch, sightings: replaceSighting(now.sightings, sighting) });
      }
    } catch {
      // The known path already shows the new species. The other has nothing
      // it can show yet, so it loads everything.
      if (!known) reload();
    }
  }, [commit, reload]);

  useEffect(() => {
    const stop = openSightingStream({
      onSighting: applyStreamed,
      onDeleted: applyDeleted,
      onUpdated: applyUpdated,
      onResync: reload,
      onStatus: setLive,
      onAuthError: () => {
        hasData.current = false;
        rawRef.current = null;
        setData(null);
        onAuthError?.();
      },
    });
    return stop;
  }, [applyStreamed, applyDeleted, applyUpdated, reload, onAuthError]);

  // Shallow-merge fields into the loaded dataset (e.g. after Settings saves the
  // current user), so dependent UI like the sidebar updates without a refetch.
  const patch = useCallback((partial) => {
    overridesRef.current = { ...overridesRef.current, ...partial };
    setData((d) => (d ? { ...d, ...partial } : d));
  }, []);

  return (
    <Ctx.Provider value={{ data, loading, error, live, reload, patch, applyDeleted, applyUpdated }}>
      {children}
    </Ctx.Provider>
  );
}

export function useData() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
