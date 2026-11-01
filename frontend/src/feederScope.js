// The feeder scope: which feeder Home, Species, Animals and the stats cover.
// Null means every feeder the user can see. The browser keeps the choice.

export const SCOPE_KEY = "peckdeck_feeder_scope";

/** The saved feeder id, or null for all feeders. */
export function readScope() {
  try {
    const id = Number(localStorage.getItem(SCOPE_KEY));
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null; // storage blocked
  }
}

export function saveScope(id) {
  try {
    if (id == null) localStorage.removeItem(SCOPE_KEY);
    else localStorage.setItem(SCOPE_KEY, String(id));
  } catch { /* storage blocked: the choice lasts this session only */ }
}

/**
 * `id` when it names one of `devices` (raw rows or mapped), else null. A feeder
 * that was deleted, or that the user lost access to, falls back to all.
 */
export function validScope(id, devices) {
  return id != null && (devices || []).some((d) => d.id === id) ? id : null;
}

/** A path with `device_id` added when the scope is one feeder. */
export function withScope(path, deviceId) {
  if (deviceId == null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}device_id=${deviceId}`;
}
