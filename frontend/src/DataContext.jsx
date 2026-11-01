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
  applySighting, fetchAggregates, fetchRaw, fetchScopedSightings, forgetSpeciesHours, mapAll,
  removeSighting, replaceSighting,
} from "./data.js";
import { openSightingStream } from "./events.js";
import { readScope, saveScope, validScope } from "./feederScope.js";

const Ctx = createContext(null);

// `raw` with `fn` applied to both sighting lists. The same object when neither
// changed.
function rowsWith(raw, fn) {
  const sightings = fn(raw.sightings);
  const scopedSightings = raw.scopedSightings && fn(raw.scopedSightings);
  if (sightings === raw.sightings && scopedSightings === raw.scopedSightings) return raw;
  return { ...raw, sightings, scopedSightings };
}

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
  // Versions of updated sightings already applied, as
  // "id@corrected_at@weather". The tab that made a change applies it itself,
  // then hears it again on the stream.
  const appliedRef = useRef(new Set());
  // History's listeners. History holds its own pages beyond the loaded window,
  // so each streamed change goes to it as well.
  const listenersRef = useRef(new Set());
  const notify = useCallback((event) => {
    for (const listener of listenersRef.current) listener(event);
  }, []);
  const subscribe = useCallback((listener) => {
    listenersRef.current.add(listener);
    return () => { listenersRef.current.delete(listener); };
  }, []);

  // The feeder scope, null for all feeders. The ref is what fetches read, so a
  // fetch in flight can tell the picker moved while it waited.
  const [feeder, setFeederState] = useState(readScope);
  const feederRef = useRef(feeder);

  const setScope = useCallback((id) => {
    feederRef.current = id;
    setFeederState(id);
    saveScope(id);
  }, []);

  // The aggregates for the current scope, and with `withSightings` the scoped
  // sightings too. If the scope changed while they loaded, the scoped fields
  // are dropped, and the picker's own fetch brings the new ones.
  const fetchScoped = useCallback(async ({ withSightings = false, ...opts } = {}) => {
    const deviceId = feederRef.current;
    const [patch, scoped] = await Promise.all([
      fetchAggregates({ ...opts, deviceId }),
      withSightings ? fetchScopedSightings(deviceId) : undefined,
    ]);
    if (feederRef.current !== deviceId) {
      const rest = { ...patch };
      delete rest.counts;
      delete rest.heatmap;
      delete rest.dashboard;
      return rest;
    }
    if (!withSightings) return patch;
    // A visit that streamed in while the list loaded is in the full list
    // already. Carry it over, or it would be lost until the next load.
    let scopedSightings = scoped;
    if (scoped) {
      for (const row of rawRef.current?.sightings || []) {
        if (row.device_id === deviceId) scopedSightings = applySighting(scopedSightings, row);
      }
    }
    return { ...patch, scopedSightings };
  }, []);

  const commit = useCallback((raw) => {
    rawRef.current = raw;
    setData({ ...mapAll(raw), ...overridesRef.current });
    hasData.current = true;
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const asked = feederRef.current;
      let raw = await fetchRaw({ deviceId: asked });
      // A saved feeder that is gone, or no longer shared, falls back to all.
      // The picker may also have moved while this loaded.
      const scope = validScope(feederRef.current, raw.devices);
      if (scope !== feederRef.current) setScope(scope);
      if (scope !== asked) {
        const [patch, scopedSightings] = await Promise.all([
          fetchAggregates({ deviceId: scope }), fetchScopedSightings(scope),
        ]);
        raw = { ...raw, ...patch, scopedSightings };
      }
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
  }, [commit, onAuthError, setScope]);

  useEffect(() => { reload(); }, [reload]);

  // Apply one streamed sighting: prepend the row we were handed, then refetch
  // only what it invalidated.
  const applyStreamed = useCallback(async (sighting) => {
    notify({ type: "sighting", sighting });
    const raw = rawRef.current;
    // Nothing loaded yet — the reload in flight will include this sighting
    // anyway, so there is nothing to patch onto.
    if (!raw) return;

    const sightings = applySighting(raw.sightings, sighting);
    if (sightings === raw.sightings) return; // already had it (replay overlap)
    // The scoped list takes only its own feeder's visits.
    const inScope = raw.scopedSightings && sighting.device_id === feederRef.current;
    const scopedSightings = inScope
      ? applySighting(raw.scopedSightings, sighting) : raw.scopedSightings;

    // Paint the new visit immediately, then let the aggregates catch up. Waiting
    // for the refetch would put a network round trip between the bird arriving
    // and the feed showing it, which is the latency this whole change removes.
    commit({ ...raw, sightings, scopedSightings });

    try {
      const known = raw.species.some((s) => s.id === sighting.species_id);
      const patch = await fetchScoped({ withSpecies: !known });
      commit({ ...rawRef.current, ...patch });
    } catch {
      // The feed is already correct; the aggregates are merely a few visits
      // behind and the next event or manual refresh fixes them.
    }
  }, [commit, notify, fetchScoped]);

  // Drop a deleted sighting. The tab that deleted it calls this itself, so it
  // updates with the stream down. Every other tab gets it from the stream.
  const applyDeleted = useCallback(async (id) => {
    notify({ type: "deleted", id });
    const raw = rawRef.current;
    if (!raw) return;

    const next = rowsWith(raw, (rows) => removeSighting(rows, id));
    if (next === raw) return; // not held, or already dropped

    commit(next);

    try {
      const patch = await fetchScoped();
      commit({ ...rawRef.current, ...patch });
    } catch {
      // As for a new sighting: the feed is right, the counts catch up later.
    }
  }, [commit, notify, fetchScoped]);

  // Swap in an updated sighting, such as a corrected species. Applied whether
  // or not the row is in the loaded window, because the counts move either way.
  const applyUpdated = useCallback(async (sighting) => {
    const raw = rawRef.current;
    if (!raw) return;
    const version = `${sighting.id}@${sighting.corrected_at}@${sighting.weather_conditions}`
      + `@${sighting.rechecked_at}@${sighting.tier2_recheck}`;
    if (appliedRef.current.has(version)) return;
    appliedRef.current.add(version);
    notify({ type: "updated", sighting });

    // No new correction, such as the weather landing after the upload. No
    // count moves, so there is nothing to refetch.
    const swap = (r) => rowsWith(r, (rows) => replaceSighting(rows, sighting));
    const prior = [...raw.sightings, ...(raw.scopedSightings || [])]
      .find((s) => s.id === sighting.id);
    if (prior && prior.species_id === sighting.species_id
      && prior.corrected_at === sighting.corrected_at) {
      commit(swap(raw));
      return;
    }
    forgetSpeciesHours();

    const known = raw.species.some((s) => s.id === sighting.species_id);
    try {
      if (known) {
        commit(swap(raw));
        const patch = await fetchScoped();
        commit({ ...rawRef.current, ...patch });
      } else {
        // mapAll drops a sighting it can't join to a species, which would also
        // close it in the detail view. So the species list comes first.
        const patch = await fetchScoped({ withSpecies: true });
        commit(swap({ ...rawRef.current, ...patch }));
      }
    } catch {
      // The known path already shows the new species. The other has nothing
      // it can show yet, so it loads everything.
      if (!known) reload();
    }
  }, [commit, notify, reload, fetchScoped]);

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

  // Pick the feeder scope, null for all. The full sightings list stays. The
  // aggregates and the scoped sightings are fetched again.
  const setFeeder = useCallback(async (id) => {
    if (id === feederRef.current) return;
    setScope(id);
    if (!rawRef.current) return;
    try {
      // Awaited first. A spread before the await would read rawRef too early,
      // and write back a list from before the fetch.
      const patch = await fetchScoped({ withSightings: true });
      commit({ ...rawRef.current, ...patch });
    } catch {
      // The counts would say the old feeder under the new name. A full load
      // either fixes them or shows the error.
      reload();
    }
  }, [commit, fetchScoped, reload, setScope]);

  // Shallow-merge fields into the loaded dataset (e.g. after Settings saves the
  // current user), so dependent UI like the sidebar updates without a refetch.
  const patch = useCallback((partial) => {
    overridesRef.current = { ...overridesRef.current, ...partial };
    setData((d) => (d ? { ...d, ...partial } : d));
  }, []);

  return (
    <Ctx.Provider value={{
      data, loading, error, live, reload, patch, applyDeleted, applyUpdated, subscribe,
      feeder, setFeeder,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export function useData() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
