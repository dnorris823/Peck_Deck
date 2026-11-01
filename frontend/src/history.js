// History's own list of sightings. Home keeps the newest 100 for live updates
// (SIGHTING_WINDOW in data.js). History asks the server instead, one page at a
// time, so "30 days" or a species filter reaches past those 100.
import { apiGet } from "./api.js";
import { removeSighting, replaceSighting } from "./data.js";

export const HISTORY_PAGE = 100;

/**
 * True when a raw sighting row passes History's filters, `{ deviceId,
 * speciesId, from, to }`. The ids are null for "all". `from` and `to` are ms
 * since epoch, `to` exclusive, and null for no bound.
 */
export function matchesHistory(filters, row) {
  const t = Date.parse(row.datetime);
  return (filters.deviceId == null || row.device_id === filters.deviceId)
    && (filters.speciesId == null || row.species_id === filters.speciesId)
    && (filters.from == null || t >= filters.from)
    && (filters.to == null || t < filters.to);
}

/**
 * The query for the page after `loaded`, the raw rows held so far, newest
 * first.
 *
 * The next page starts at the oldest loaded row's timestamp rather than at an
 * offset from the top. A sighting that streams in, or one deleted in another
 * tab, shifts every offset by one, which would repeat or skip a visit at the
 * page boundary. The small offset skips the rows already held at that exact
 * timestamp. The server breaks ties by id, so that count is stable.
 */
export function historyParams(filters, loaded = []) {
  const params = new URLSearchParams({ limit: String(HISTORY_PAGE) });
  if (filters.deviceId != null) params.set("device_id", String(filters.deviceId));
  if (filters.speciesId != null) params.set("species_id", String(filters.speciesId));
  if (filters.from != null) params.set("from_date", new Date(filters.from).toISOString());
  const oldest = loaded[loaded.length - 1];
  if (oldest) {
    // The raw string, not a Date. The server keeps microseconds, and a Date
    // rounded to the millisecond would skip rows inside that millisecond.
    params.set("to_date", oldest.datetime);
    const ties = loaded.filter((s) => s.datetime === oldest.datetime).length;
    params.set("offset", String(ties));
  } else if (filters.to != null) {
    // The server's to_date is inclusive.
    params.set("to_date", new Date(filters.to - 1).toISOString());
  }
  return params;
}

/** The next page of raw rows, and whether it was the last. */
export async function fetchHistoryPage(filters, loaded = []) {
  const rows = await apiGet(`/sightings?${historyParams(filters, loaded)}`);
  return { rows, done: rows.length < HISTORY_PAGE };
}

/** Add rows the list does not hold yet, keeping it newest first. */
export function mergeRows(rows, more) {
  const held = new Set(rows.map((s) => s.id));
  const added = more.filter((s) => !held.has(s.id));
  if (added.length === 0) return rows;
  // Parsed rather than compared as strings, as in applySighting.
  return [...rows, ...added].sort((a, b) => Date.parse(b.datetime) - Date.parse(a.datetime));
}

/**
 * Apply one change from the live stream to History's list, `{ rows, done }`.
 * Returns the same object when nothing changed.
 *
 * A new sighting goes in only when it is newer than the oldest loaded row, or
 * the list holds every page. An older one arrives with the next page, and
 * putting it in now would move the point that page starts from.
 */
export function applyHistoryEvent(list, event, filters) {
  if (event.type === "deleted") {
    const rows = removeSighting(list.rows, event.id);
    return rows === list.rows ? list : { ...list, rows };
  }
  if (event.type === "updated") {
    const rows = replaceSighting(list.rows, event.sighting);
    return rows === list.rows ? list : { ...list, rows };
  }
  if (event.type === "sighting") {
    const s = event.sighting;
    if (!matchesHistory(filters, s)) return list;
    const oldest = list.rows[list.rows.length - 1];
    const inSpan = list.done || (oldest && Date.parse(s.datetime) > Date.parse(oldest.datetime));
    if (!inSpan) return list;
    const rows = mergeRows(list.rows, [s]);
    return rows === list.rows ? list : { ...list, rows };
  }
  return list;
}
