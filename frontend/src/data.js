// === Data layer — Peck Deck ===
// Adapts the Litestar backend's responses into the shapes the pages expect
// (the same shapes the original design fixtures used, so pages barely changed).
// `loadAll()` fetches everything in parallel; DataContext calls it after login.

import { apiDelete, apiDownload, apiGet, apiSend } from "./api.js";
import { withScope } from "./feederScope.js";

// ── Fallbacks for presentation-only fields ────────────────────────────────
// The backend carries palette/silhouette/note (see seed.py), but a species
// created ad hoc by the Pi may lack them. An empty palette stays empty, so the
// accent (accent.js) can tell "no palette" from a real one. BirdPlate has its
// own fallback colours.
// Avatar grounds. Fixed colours, each with white initials at 4.5:1 or better.
export const AV_COLORS = ["#a6533d", "#3f6e89", "#56663a", "#86641d", "#6b4570"];

export function initials(name) {
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
    palette: Array.isArray(s.palette) ? s.palette : [],
    silhouette: s.silhouette || "songbird",
    wiki: s.wiki_url || null,
    ebird: s.ebird_code || null,
    note: s.note || "",
    // "animal" for a squirrel or other feeder mammal Tier 2 named. A backend
    // without the field only has birds.
    kind: s.kind || "bird",
    animalGroup: s.animal_group || null,
  };
}

/** True for a bird visit. Home and the bird counts leave animal visits out. */
export function isBirdSighting(s) {
  return s.species?.kind !== "animal";
}

function mapSpeciesCount(s) {
  return {
    ...mapSpecies(s),
    count: s.count,
    firstSeen: s.first_seen ? fmtDateFull(new Date(s.first_seen)) : "—",
    firstSeenAt: s.first_seen ? new Date(s.first_seen) : null,
    lastSeenAt: s.last_seen ? new Date(s.last_seen) : null,
    // Local hours with the most visits over 30 days, busiest first. Null when
    // the request sent no time zone.
    peakHours: Array.isArray(s.peak_hours) ? s.peak_hours : null,
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
    // "mains", "battery", or null from a Pi that does not say.
    powerSource: d.power_source || null,
    signal: d.signal || "none",
    lastSeen: d.last_seen ? fmtRelative(new Date(d.last_seen)) : "never",
    lastSeenAt: d.last_seen ? new Date(d.last_seen) : null,
    // Whether the feeder can stream now. A backend without the field says no.
    liveAvailable: !!d.live_available,
    todaySightings: d.today_sightings,
    weekSightings: d.week_sightings,
    allTime: d.all_time_sightings,
    ownerId: d.owner_id,
    tierMix: d.tier_mix ? mapTierMix(d.tier_mix) : null,
    feedState: d.feed ? mapFeed(d.feed) : null,
  };
}

// ok, low or out, from the backend's hourly feed check. See backend/feed/monitor.py.
function mapFeed(f) {
  const at = (v) => (v ? new Date(v) : null);
  return {
    state: f.state,
    changedAt: at(f.changed_at),
    lastRefillAt: at(f.last_refill_at),
    lastVisitAt: at(f.last_visit_at),
  };
}

// Which tier named the feeder's recent captures. `tier2Down` means Tier 2 has
// stopped answering; the backend decides that from each sighting's trace.
function mapTierMix(m) {
  return {
    hours: m.window_hours,
    counts: { gpu: m.gpu, local: m.local, cloud: m.cloud, none: m.none },
    tier2Asked: m.tier2_asked,
    tier2Missed: m.tier2_missed,
    tier2Down: m.tier2_warning,
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

export function mapSighting(s, speciesById, devicesById) {
  return {
    id: s.id,
    species: speciesById.get(s.species_id),
    device: devicesById.get(s.device_id),
    datetime: new Date(s.datetime),
    confidence: s.confidence_score,
    tier: s.classification_tier_used,
    hasImage: s.has_image,
    hasVideo: false, // no video pipeline yet — kept for the tile's clip badge
    // True when the Pi's offline queue sent it after the fact.
    delayed: !!s.delayed,
    // Such as "4 °C, light snow", from Open-Meteo a moment after the upload.
    // Null until then, and for a device with no city.
    weather: s.weather_conditions || null,
    // What each tier did, in chain order. Null for sightings from before the Pi
    // sent a trace.
    tierTrace: Array.isArray(s.tier_trace) ? s.tier_trace : null,
    // Set when a person corrected the species. `species` is then their answer,
    // and `originalSpecies` is what the tier named. Null when nobody has.
    originalSpecies: s.original_species_id == null
      ? null : speciesById.get(s.original_species_id) || null,
    correctedBy: s.corrected_by ?? null,
    correctedAt: s.corrected_at ? new Date(s.corrected_at) : null,
    // True while the species is the Pi's fallback, waiting for the GPU tier to
    // re-check it once the inference server is back. It may still change.
    provisional: s.tier2_recheck === "pending",
    // The species the Pi named, when the GPU re-check replaced it. Null
    // otherwise.
    provisionalSpecies: s.provisional_species_id == null
      ? null : speciesById.get(s.provisional_species_id) || null,
    recheckedAt: s.rechecked_at ? new Date(s.rechecked_at) : null,
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

/** The browser's IANA time zone, such as "America/Los_Angeles". */
export function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// Sent with the viewer's zone, so each row's peak_hours are local hours.
// `deviceId` scopes the counts to one feeder. Null covers them all.
export function speciesCountsPath(zone = browserZone(), deviceId = null) {
  return withScope(`/stats/species-counts?tz=${encodeURIComponent(zone)}`, deviceId);
}

/**
 * Visits per species between two times, inclusive, as `[{ common, count }]`.
 * Counted by the backend, so a busy day past the loaded window still adds up.
 */
export async function fetchSpeciesCountsBetween(start, end, deviceId = null) {
  const params = new URLSearchParams({ from_date: start.toISOString(), to_date: end.toISOString() });
  const rows = await apiGet(withScope(`/stats/species-counts?${params}`, deviceId));
  return rows.map(r => ({ id: r.id, common: r.common_name, count: r.count }));
}

// ── Loader ────────────────────────────────────────────────────────────────
// Fetch and mapping are separate so a streamed sighting can patch the *raw*
// payloads and re-map them through this same function. Mapping is not
// reversible (it produces Date objects), so the raw set has to be kept.
//
// `deviceId` is the feeder scope (feederScope.js). It scopes the aggregates
// only. The sightings list covers every feeder, and pages filter it.
export async function fetchRaw({ deviceId = null } = {}) {
  const [species, counts, devices, users, sightings, heatmap, dashboard, me, prefs] =
    await Promise.all([
      apiGet("/species"),
      apiGet(speciesCountsPath(browserZone(), deviceId)),
      apiGet("/devices"),
      // Owner only. A viewer gets 403 and an empty list, and never sees Users.
      apiGet("/users").catch((e) => {
        if (e.status === 403) return [];
        throw e;
      }),
      apiGet("/sightings?limit=100"),
      apiGet(withScope("/stats/heatmap", deviceId)),
      apiGet(withScope("/stats/dashboard", deviceId)),
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
export async function fetchAggregates({ withSpecies = false, deviceId = null } = {}) {
  const [counts, heatmap, dashboard, devices, species] = await Promise.all([
    apiGet(speciesCountsPath(browserZone(), deviceId)),
    apiGet(withScope("/stats/heatmap", deviceId)),
    apiGet(withScope("/stats/dashboard", deviceId)),
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

// Swap in a sighting's new version, such as a corrected species. Returns the
// same array when the id is absent.
export function replaceSighting(rawSightings, sighting) {
  if (!rawSightings.some((s) => s.id === sighting.id)) return rawSightings;
  return rawSightings.map((s) => (s.id === sighting.id ? sighting : s));
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

  // Backend returns raw hourly counts, clamped here to levels 0 to 4.
  const HEATMAP = heatmap.map(row => row.map(v => Math.min(4, v)));

  return {
    SPECIES, SPECIES_COUNTS, DEVICES, USERS, SIGHTINGS, HEATMAP,
    DASHBOARD: dashboard, ME: mapMe(me), PREFERENCES: prefs,
  };
}

export async function loadAll() {
  return mapAll(await fetchRaw());
}

/**
 * Fetch one sighting by id and map it against the loaded species and feeders.
 * For a sighting outside the loaded window, such as an old push notification.
 * Resolves to null when the sighting names a species or feeder this client has
 * not loaded, the same rule mapAll applies.
 */
export async function fetchSighting(id, data) {
  return mapAgainst(await apiGet(`/sightings/${id}`), data);
}

/** Map one raw sighting against a loaded dataset, or null if it can't join. */
export function mapAgainst(raw, data) {
  const s = mapSighting(
    raw,
    new Map(data.SPECIES.map(x => [x.id, x])),
    new Map(data.DEVICES.map(d => [d.id, d])),
  );
  return s.species && s.device ? s : null;
}

// A species' busy hours barely move within a session, so each species is
// asked once.
const hourStatsCache = new Map();

/** Visits per local hour for one species over the last 30 days, cached. */
export function fetchSpeciesHours(speciesId) {
  if (!hourStatsCache.has(speciesId)) {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const params = new URLSearchParams({ species_id: String(speciesId), days: "30", tz });
    const pending = apiGet(`/stats/hours?${params}`).catch((e) => {
      hourStatsCache.delete(speciesId); // a failure is worth a retry next time
      throw e;
    });
    hourStatsCache.set(speciesId, pending);
  }
  return hourStatsCache.get(speciesId);
}

// A corrected sighting moves a visit between two species' hours.
export function forgetSpeciesHours() {
  hourStatsCache.clear();
}

export async function deleteSighting(id) {
  return apiDelete(`/sightings/${id}`);
}

// Many at once, as `{ deleted }`. All or nothing: one sighting on a feeder the
// user cannot manage refuses the lot with 403.
export async function deleteSightings(ids) {
  return apiSend("/sightings/delete", "POST", { ids });
}

// `{ count }` of the feeder's sightings older than `before`, a Date.
export async function countSightingsBefore(deviceId, before) {
  return apiGet(`/devices/${deviceId}/sightings/count?before=${encodeURIComponent(before.toISOString())}`);
}

export async function deleteSightingsBefore(deviceId, before) {
  return apiDelete(`/devices/${deviceId}/sightings?before=${encodeURIComponent(before.toISOString())}`);
}

// Set the species a person says this is. Resolves to the raw updated row.
export async function correctSighting(id, speciesId) {
  return apiSend(`/sightings/${id}`, "PATCH", { species_id: speciesId });
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

// ── Storage ───────────────────────────────────────────────────────────────
// Database size, image size, and the retention rule's age in days (0 is off).
export async function fetchStorage() {
  return apiGet("/stats/storage");
}

// A byte count as a short size in base 1024, such as "512 B" or "3.4 MB".
export function formatBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return i === 0 ? `${value} B` : `${value.toFixed(1)} ${units[i]}`;
}

// ── CRUD mutations (Users / Devices / Species) ────────────────────────────
// Invite a user. Owner only. Needs name, email and password, and takes a role.
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

// Owner only, like the two below. Takes effect on the user's next request.
export async function setUserRole(userId, role) {
  return apiSend(`/users/${userId}/role`, "PUT", { role });
}

// Revokes every token the user holds. Their password still works.
export async function signOutUser(userId) {
  return apiSend(`/users/${userId}/logout`, "POST", {});
}

// Refused with 409 for a feeder owner or the last owner.
export async function deleteUser(userId) {
  return apiDelete(`/users/${userId}`);
}

// Register a device — the backend returns the full device INCLUDING its token,
// which is shown once so the Pi can be provisioned.
export async function createDevice(body) {
  return apiSend("/devices", "POST", body);
}

// Change a feeder's name, city, state or feed type. An empty string clears a field.
export async function updateDevice(deviceId, patch) {
  return apiSend(`/devices/${deviceId}`, "PUT", patch);
}

// Feeder owner or owner role only. `{ id, token }`, for the Pi's DEVICE_TOKEN.
export async function fetchDeviceToken(deviceId) {
  return apiGet(`/devices/${deviceId}/token`);
}

// Mints a new token. The old one fails at once, so the Pi stops uploading
// until it has the new one.
export async function rotateDeviceToken(deviceId) {
  return apiSend(`/devices/${deviceId}/token`, "POST", {});
}

// ── Animals ───────────────────────────────────────────────────────────────
// Daily animal visits per group on one feeder, with its measures and their
// effect. The last 60 days by default, in the viewer's time zone.
export async function fetchAnimalStats(deviceId, zone = browserZone()) {
  const params = new URLSearchParams({ device_id: String(deviceId), tz: zone });
  return apiGet(`/stats/animals?${params}`);
}

// The measure routes are feeder owner or owner role only.
export async function createMeasure(deviceId, body) {
  return apiSend(`/devices/${deviceId}/measures`, "POST", body);
}

export async function updateMeasure(deviceId, measureId, patch) {
  return apiSend(`/devices/${deviceId}/measures/${measureId}`, "PATCH", patch);
}

export async function deleteMeasure(deviceId, measureId) {
  return apiDelete(`/devices/${deviceId}/measures/${measureId}`);
}

// Feeder owner or owner role only. Ends any low or out alert. Returns the feeder.
export async function logRefill(deviceId) {
  return apiSend(`/devices/${deviceId}/refills`, "POST", {});
}

// Without `withSightings` the server refuses a feeder that has sightings (409).
// With it, the sightings and their photos are deleted too.
export async function deleteDevice(deviceId, { withSightings = false } = {}) {
  return apiDelete(`/devices/${deviceId}${withSightings ? "?delete_sightings=true" : ""}`);
}

// The feeder's owner and members, as `{ owner, members }`. They get its alerts.
export async function fetchFeederAccess(deviceId) {
  return apiGet(`/devices/${deviceId}/users`);
}

// Add a member by `{ user_id }`, or by `{ email }` for a viewer who owns a feeder.
export async function addFeederMember(deviceId, who) {
  return apiSend(`/devices/${deviceId}/users`, "POST", who);
}

export async function removeFeederMember(deviceId, userId) {
  return apiDelete(`/devices/${deviceId}/users/${userId}`);
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
  gpu: { short: "GPU", long: "Gaming PC GPU", threshold: 0.6 },
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
