// === Data layer — Peck Deck ===
// Adapts the Litestar backend's responses into the shapes the pages expect
// (the same shapes the original design fixtures used, so pages barely changed).
// `loadAll()` fetches everything in parallel; DataContext calls it after login.

import { apiDelete, apiDownload, apiGet, apiSend } from "./api.js";

// ── Fallbacks for presentation-only fields ────────────────────────────────
// The backend now carries palette/silhouette/note (see seed.py), but a species
// created ad-hoc by the Pi may lack them — fall back so BirdPlate still renders.
const DEFAULT_PALETTE = ["#7a8a8c", "#2a3032", "#d4cdb8"];
const AV_COLORS = [
  "var(--cardinal)", "var(--forest)", "var(--sky-deep)", "var(--yolk-deep)", "var(--plum)",
];

function initials(name) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// ── Row mappers (snake_case backend → camelCase UI) ───────────────────────
function mapSpecies(s) {
  return {
    id: s.id,
    common: s.common_name,
    sci: `${s.genus} ${s.species_name}`.trim(),
    order: s.order_name || "—",
    palette: s.palette && s.palette.length ? s.palette : DEFAULT_PALETTE,
    silhouette: s.silhouette || "songbird",
    wiki: s.wiki_url || null,
    note: s.note || "",
  };
}

function mapSpeciesCount(s) {
  return {
    ...mapSpecies(s),
    count: s.count,
    firstSeen: s.first_seen ? fmtDateFull(new Date(s.first_seen)) : "—",
  };
}

function mapDevice(d) {
  return {
    id: d.id,
    name: d.name,
    city: d.city || "—",
    state: d.state || "",
    feed: d.feed_type || "—",
    status: d.status,
    // Null means the station reports no battery (mains power). Mapping it to 0
    // drew a red "0%" on every plugged-in Pi.
    battery: d.battery == null ? null : d.battery,
    signal: d.signal || "none",
    lastSeen: d.last_seen ? fmtRelative(new Date(d.last_seen)) : "never",
    todaySightings: d.today_sightings,
    weekSightings: d.week_sightings,
    allTime: d.all_time_sightings,
    ownerId: d.owner_id,
  };
}

function mapUser(u, i) {
  return {
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    notify_email: u.notify_email,
    av: initials(u.name),
    avBg: AV_COLORS[i % AV_COLORS.length],
  };
}

function mapSighting(s, speciesById, devicesById) {
  return {
    id: s.id,
    species: speciesById.get(s.species_id),
    device: devicesById.get(s.device_id),
    datetime: new Date(s.datetime),
    confidence: s.confidence_score,
    tier: s.classification_tier_used,
    hasImage: s.has_image,
    hasVideo: false, // no video pipeline yet — kept for the tile's clip badge
  };
}

// The authenticated user, kept close to its raw backend shape (snake_case)
// since Settings persists directly against these fields.
function mapMe(u) {
  return {
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    notify_email: u.notify_email,
  };
}

// ── Loader ────────────────────────────────────────────────────────────────
// Fetch and mapping are separate so a streamed sighting can patch the *raw*
// payloads and re-map them through this same function. Mapping is not
// reversible (it produces Date objects), so the raw set has to be kept.
export async function fetchRaw() {
  const [species, counts, devices, users, sightings, heatmap, dashboard, me, prefs] =
    await Promise.all([
      apiGet("/species"),
      apiGet("/stats/species-counts"),
      apiGet("/devices"),
      apiGet("/users"),
      apiGet("/sightings?limit=100"),
      apiGet("/stats/heatmap"),
      apiGet("/stats/dashboard"),
      apiGet("/users/me"),
      apiGet("/users/me/preferences"),
    ]);
  return { species, counts, devices, users, sightings, heatmap, dashboard, me, prefs };
}

// The subset that a single new sighting invalidates. The streamed event carries
// the sighting row itself, so the feed needs no refetch at all — but every
// aggregate derived from it is now stale, and recomputing them in the browser
// would mean a second implementation of the backend's aggregation drifting
// against the first. Refetching these four costs ~9 KB against the ~37 KB of a
// full reload.
//
// `species` is only pulled when the streamed sighting names one the client has
// never seen: mapAll drops any sighting it can't join to a species, so a
// first-ever visit would otherwise arrive and silently vanish.
export async function fetchAggregates({ withSpecies = false } = {}) {
  const [counts, heatmap, dashboard, devices, species] = await Promise.all([
    apiGet("/stats/species-counts"),
    apiGet("/stats/heatmap"),
    apiGet("/stats/dashboard"),
    apiGet("/devices"),
    withSpecies ? apiGet("/species") : Promise.resolve(null),
  ]);
  const patch = { counts, heatmap, dashboard, devices };
  return species ? { ...patch, species } : patch;
}

// How many sightings the client keeps. Matches the `limit` in fetchRaw, so a
// streamed prepend can't grow the list past what a reload would produce.
export const SIGHTING_WINDOW = 100;

/**
 * Insert a streamed sighting into the raw list, keeping it newest-first.
 *
 * Inserted by timestamp rather than prepended, because "newest id" and "newest
 * datetime" are not the same thing here: the Pi's offline queue uploads
 * backdated captures once it reconnects, so a visit from this morning can
 * arrive with the highest id on the server. Prepending would file it above
 * visits that actually happened later, and nothing would correct the order
 * until a full reload.
 */
export function applySighting(rawSightings, sighting) {
  if (rawSightings.some((s) => s.id === sighting.id)) return rawSightings;
  // Parsed rather than compared as strings: these are raw ISO-8601 payloads,
  // and lexicographic order only matches chronological order while every one
  // of them carries the same UTC offset.
  const arrived = Date.parse(sighting.datetime);
  const at = rawSightings.findIndex((s) => Date.parse(s.datetime) < arrived);
  const index = at === -1 ? rawSightings.length : at;
  return [
    ...rawSightings.slice(0, index),
    sighting,
    ...rawSightings.slice(index),
  ].slice(0, SIGHTING_WINDOW);
}

// Drop a deleted sighting from the raw list. Returns the same array when the id
// is absent, so the tab that deleted it skips the work when its own stream
// event arrives.
export function removeSighting(rawSightings, id) {
  if (!rawSightings.some((s) => s.id === id)) return rawSightings;
  return rawSightings.filter((s) => s.id !== id);
}

export function mapAll(raw) {
  const { species, counts, devices, users, sightings, heatmap, dashboard, me, prefs } = raw;

  const SPECIES = species.map(mapSpecies);
  const SPECIES_COUNTS = counts.map(mapSpeciesCount);
  const DEVICES = devices.map(mapDevice);
  const USERS = users.map(mapUser);

  const speciesById = new Map(SPECIES.map(s => [s.id, s]));
  const devicesById = new Map(DEVICES.map(d => [d.id, d]));
  const SIGHTINGS = sightings
    .map(s => mapSighting(s, speciesById, devicesById))
    .filter(s => s.species && s.device);

  // Backend returns raw hourly counts; the heatmap CSS defines heat-0..heat-4.
  const HEATMAP = heatmap.map(row => row.map(v => Math.min(4, v)));

  return {
    SPECIES, SPECIES_COUNTS, DEVICES, USERS, SIGHTINGS, HEATMAP,
    DASHBOARD: dashboard, ME: mapMe(me), PREFERENCES: prefs,
  };
}

export async function loadAll() {
  return mapAll(await fetchRaw());
}

export async function deleteSighting(id) {
  return apiDelete(`/sightings/${id}`);
}

// ── Settings mutations ────────────────────────────────────────────────────
// Persist account/notification fields on the current user. Accepts any subset
// of {name, email, notify_email}; returns the updated (mapped) user.
export async function saveMe(userId, patch) {
  const updated = await apiSend(`/users/${userId}`, "PUT", patch);
  return mapMe(updated);
}

// Persist a subset of the user's preferences; returns the full updated set.
export async function savePreferences(patch) {
  return apiSend("/users/me/preferences", "PUT", patch);
}

// ── CRUD mutations (Users / Devices / Species) ────────────────────────────
// Register a new user (public endpoint — needs name+email+password, optional role).
export async function createUser(body) {
  return apiSend("/users", "POST", body);
}

// Update an existing user's editable fields (name/notify/email).
export async function updateUser(userId, patch) {
  return apiSend(`/users/${userId}`, "PUT", patch);
}

// Change a user's password. Self-change needs current_password; owner reset omits it.
export async function changePassword(userId, body) {
  return apiSend(`/users/${userId}/password`, "POST", body);
}

// Register a device — the backend returns the full device INCLUDING its token,
// which is shown once so the Pi can be provisioned.
export async function createDevice(body) {
  return apiSend("/devices", "POST", body);
}

// Add a species to the library.
export async function createSpecies(body) {
  return apiSend("/species", "POST", body);
}

// Build the authenticated export URL. Returned as a blob rather than a plain
// link because the endpoint needs the Bearer token, which an <a href> can't
// carry.
export async function downloadExport({ fmt = "csv", deviceId = null, days = null } = {}) {
  const params = new URLSearchParams({ fmt });
  if (deviceId != null) params.set("device_id", String(deviceId));
  if (days != null) {
    const from = new Date(Date.now() - days * 86400000).toISOString();
    params.set("from_date", from);
  }
  return apiDownload(`/sightings/export?${params}`);
}

// ── Date/time formatting helpers (unchanged API; now use real "now") ──────
export function fmtTime(d) {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}
export function fmtRelative(d) {
  const diff = (Date.now() - d.getTime()) / 60000; // minutes
  if (diff < 1) return "just now";
  if (diff < 60) return `${Math.floor(diff)}m ago`;
  if (diff < 60 * 24) return `${Math.floor(diff / 60)}h ago`;
  return `${Math.floor(diff / (60 * 24))}d ago`;
}
export function fmtDateLabel(d) {
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
export function fmtDateFull(d) {
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

// ── Classification tiers ──────────────────────────────────────────────────
// Thresholds mirror DEFAULT_TIER_THRESHOLDS in raspberry_pi_code/config.py.
// A score below its tier's threshold is a guess the chain kept anyway (for
// example the last tier standing), so the UI marks it as unsure rather than
// colouring every tier against one shared scale.
export const TIERS = {
  local: { short: "Pi", long: "On the Pi (TFLite)", threshold: 0.85 },
  gpu: { short: "PC", long: "Gaming PC GPU", threshold: 0.6 },
  cloud: { short: "Claude", long: "Claude API", threshold: 0.5 },
  none: { short: "None", long: "No tier answered", threshold: Infinity },
};

export function tierInfo(tier) {
  return TIERS[tier] || { short: tier || "?", long: tier || "Unknown tier", threshold: Infinity };
}

/** "sure" when the score clears its own tier's threshold, else "unsure". */
export function confidenceLevel(s) {
  return s.confidence >= tierInfo(s.tier).threshold ? "sure" : "unsure";
}

// ── Local-time helpers ────────────────────────────────────────────────────
// The backend buckets by UTC, so on the US west coast an afternoon visit lands
// on tomorrow's row. These re-bucket in the viewer's own time zone.

export function startOfToday(now = new Date()) {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** Sightings since local midnight, from the loaded window. */
export function countToday(sightings, now = new Date()) {
  const cutoff = startOfToday(now).getTime();
  return sightings.filter((s) => s.datetime.getTime() >= cutoff).length;
}

/**
 * Shift a Mon→Sun × 24h grid from UTC into local time. Rotating cells by the
 * offset is exact for whole-hour zones; half-hour zones round to the nearest
 * hour, which a heatmap cannot show anyway.
 */
export function toLocalGrid(grid, offsetMinutes = -new Date().getTimezoneOffset()) {
  if (grid.length !== 7 || grid.some((row) => row.length !== 24)) return grid;
  const shift = Math.round(offsetMinutes / 60);
  const out = Array.from({ length: 7 }, () => Array(24).fill(0));
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const t = (((d * 24 + h + shift) % 168) + 168) % 168;
      out[Math.floor(t / 24)][t % 24] = grid[d][h];
    }
  }
  return out;
}

/** "Today", "Yesterday", or "Tue, Oct 26" for a day-group heading. */
export function fmtDayHeading(d, now = new Date()) {
  const day = startOfToday(d).getTime();
  const today = startOfToday(now).getTime();
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}
