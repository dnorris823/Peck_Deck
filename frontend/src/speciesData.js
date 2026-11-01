// Species views: the per-species fetches and the local-time labels they show.
// Every hour here is a local hour in the browser's zone. The backend buckets by
// the `tz` the request sends, so the dial and the list agree with the clock on
// the wall.
import { apiGet } from "./api.js";
import { browserZone, mapSighting, startOfToday } from "./data.js";

// The Pi files a capture no tier could name under this species.
export function isUnknown(species) {
  return (species?.common || "").trim().toLowerCase() === "unknown";
}

/**
 * Outside pages about one species, in display order. eBird and All About Birds
 * key their pages on the eBird code, so a species outside the taxonomy gets
 * neither. Xeno-canto searches by common name, because its scientific names
 * match neither the taxonomy's nor eBird's for every bird.
 */
export function speciesLinks(species) {
  if (isUnknown(species)) return [];
  const links = [];
  if (species.wiki) links.push({ label: "Wikipedia", hint: "Background", href: species.wiki });
  if (species.ebird) {
    const code = encodeURIComponent(species.ebird);
    links.push({ label: "eBird", hint: "Range and recent sightings", href: `https://ebird.org/species/${code}` });
    links.push({ label: "All About Birds", hint: "ID guide", href: `https://www.allaboutbirds.org/guide/${code}` });
  }
  const query = encodeURIComponent(species.common);
  links.push({ label: "Xeno-canto", hint: "Songs and calls", href: `https://xeno-canto.org/explore?query=${query}` });
  return links;
}

/** Visits per local hour for one species. `days` of 0 means all time. */
export function fetchHours(speciesId, { days = 30, zone = browserZone() } = {}) {
  const params = new URLSearchParams({ species_id: String(speciesId), days: String(days), tz: zone });
  return apiGet(`/stats/hours?${params}`);
}

/**
 * The newest sightings of one species, mapped like the main feed so the
 * sighting view can open them. `data` is the DataContext payload.
 */
export async function fetchSpeciesSightings(speciesId, data, { limit = 12 } = {}) {
  const rows = await apiGet(`/sightings?species_id=${speciesId}&limit=${limit}`);
  const speciesById = new Map(data.SPECIES.map((s) => [s.id, s]));
  const devicesById = new Map(data.DEVICES.map((d) => [d.id, d]));
  return rows
    .map((s) => mapSighting(s, speciesById, devicesById))
    .filter((s) => s.species && s.device);
}

// ── Labels ────────────────────────────────────────────────────────────────

/** 0 → "12 am", 8 → "8 am", 12 → "noon", 17 → "5 pm". */
export function fmtHour(h) {
  if (h === 12) return "noon";
  if (h === 0) return "12 am";
  return h < 12 ? `${h} am` : `${h - 12} pm`;
}

/** "05:20" → "5:20 am", "19:58" → "7:58 pm". */
export function fmtClock(hhmm) {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm || "");
  if (!m) return null;
  const h = Number(m[1]);
  const suffix = h < 12 ? "am" : "pm";
  return `${h % 12 || 12}:${m[2]} ${suffix}`;
}

function partOfDay(h) {
  if (h >= 5 && h <= 10) return "mornings";
  if (h >= 11 && h <= 13) return "midday";
  if (h >= 14 && h <= 16) return "afternoons";
  if (h >= 17 && h <= 20) return "evenings";
  return "nights";
}

/**
 * When a species usually comes, from its peak hours. One peak, or two in the
 * same part of the day, reads as that part: "mornings". Two apart read as
 * their hours in clock order: "8 am, 5 pm". No peaks gives null.
 */
export function usualTime(peakHours) {
  if (!peakHours?.length) return null;
  const parts = new Set(peakHours.map(partOfDay));
  if (parts.size === 1) return partOfDay(peakHours[0]);
  return [...peakHours].sort((a, b) => a - b).map(fmtHour).join(", ");
}

const dayDiff = (d, now) => Math.round((startOfToday(now) - startOfToday(d)) / 86400000);

function fmtShortDate(d, now) {
  const opts = { month: "short", day: "numeric" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("en-US", opts);
}

function fmtClockOf(d) {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

/**
 * When a species was last here, for the list: "11 min ago", "today 2:33 pm",
 * "yesterday", "Sun" or "Oct 26". With `short`, today drops its time and the
 * first letter is upper case, for the species page's stat row.
 */
export function fmtSeen(d, now = new Date(), { short = false } = {}) {
  if (!d) return "never";
  const mins = (now - d) / 60000;
  const days = dayDiff(d, now);
  let text;
  if (mins < 1) text = "just now";
  else if (mins < 60) text = `${Math.floor(mins)} min ago`;
  else if (days === 0) text = short ? "today" : `today ${fmtClockOf(d)}`;
  else if (days === 1) text = "yesterday";
  else if (days < 7) text = d.toLocaleDateString("en-US", { weekday: "short" });
  else text = fmtShortDate(d, now);
  return short ? text[0].toUpperCase() + text.slice(1) : text;
}

/** A visit's label under its thumbnail: "5:24 pm" today, else the day. */
export function fmtVisit(d, now = new Date()) {
  const days = dayDiff(d, now);
  if (days === 0) return fmtClockOf(d);
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString("en-US", { weekday: "short" });
  return fmtShortDate(d, now);
}

/** "Jul 18", or "Jul 18, 2025" outside the current year. */
export function fmtSince(d, now = new Date()) {
  return d ? fmtShortDate(d, now) : "—";
}

/** "Sun, Oct 26, 6:02 pm", for a thumbnail's accessible name. */
export function fmtVisitFull(d) {
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day}, ${fmtClockOf(d)}`;
}
