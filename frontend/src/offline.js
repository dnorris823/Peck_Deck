// Offline-tolerant reads — FLEDGE Phase 7.
//
// Keeps the last successful set of API payloads in localStorage so the app opens
// to content on a flaky connection instead of a spinner and then an error.
//
// The *raw* responses are stored, not the mapped dataset: mapping turns strings
// into Date objects and joins sightings to species/devices, and a JSON round
// trip would silently hand the pages `datetime` as a string. Storing raw and
// re-mapping on read means the cached path produces exactly the same shapes as
// the network path — there is one mapper, not two.
//
// Writes stay online-only. This is a read cache, not a sync queue: a mutation
// replayed later against a feeder that has moved on is worse than an honest
// "you're offline" error.

const KEY = "peckdeck_snapshot";
// Bump when the shape of a cached payload changes, so an old snapshot is
// discarded rather than fed to a mapper that no longer understands it.
const SCHEMA = 1;
// A snapshot older than this is dropped: showing week-old "current" feeder
// status is worse than showing nothing.
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/** Persist raw API payloads. Never throws — a full quota must not break a load. */
export function saveSnapshot(raw, now = Date.now()) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ schema: SCHEMA, savedAt: now, raw }));
    return true;
  } catch {
    // Private mode, or the images pushed us past the quota. The app works
    // without a snapshot; it just won't open offline.
    return false;
  }
}

/**
 * The stored snapshot as `{ raw, savedAt }`, or null when there isn't a usable
 * one. A corrupt, foreign-schema or stale entry is cleared on the way out so it
 * can't be re-examined on every load.
 */
export function loadSnapshot(now = Date.now()) {
  let parsed;
  try {
    const stored = localStorage.getItem(KEY);
    if (!stored) return null;
    parsed = JSON.parse(stored);
  } catch {
    clearSnapshot();
    return null;
  }

  if (!parsed || parsed.schema !== SCHEMA || !parsed.raw) {
    clearSnapshot();
    return null;
  }
  if (typeof parsed.savedAt !== "number" || now - parsed.savedAt > MAX_AGE_MS) {
    clearSnapshot();
    return null;
  }
  return { raw: parsed.raw, savedAt: parsed.savedAt };
}

/** Drop the snapshot. Called on sign-out — it holds another user's records. */
export function clearSnapshot() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing we can do, and nothing depends on it */
  }
}
