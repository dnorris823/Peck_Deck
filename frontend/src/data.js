// === Data layer — Peck Deck ===
// Adapts the Litestar backend's responses into the shapes the pages expect
// (the same shapes the original design fixtures used, so pages barely changed).
// `loadAll()` fetches everything in parallel; DataContext calls it after login.

import { apiGet, apiSend } from "./api.js";

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
    tier: d.classification_tier,
    feed: d.feed_type || "—",
    status: d.status,
    battery: d.battery == null ? 0 : d.battery,
    signal: d.signal || "none",
    lastSeen: d.last_seen ? fmtRelative(new Date(d.last_seen)) : "never",
    todaySightings: d.today_sightings,
    weekSightings: d.week_sightings,
    allTime: d.all_time_sightings,
  };
}

function mapUser(u, i) {
  return {
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    phone: u.phone || "—",
    notify_email: u.notify_email,
    notify_sms: u.notify_sms,
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
    phone: u.phone || "",
    notify_email: u.notify_email,
    notify_sms: u.notify_sms,
  };
}

// ── Loader ────────────────────────────────────────────────────────────────
export async function loadAll() {
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

// ── Settings mutations ────────────────────────────────────────────────────
// Persist account/notification fields on the current user. Accepts any subset
// of {name, phone, notify_email, notify_sms}; returns the updated (mapped) user.
export async function saveMe(userId, patch) {
  const updated = await apiSend(`/users/${userId}`, "PUT", patch);
  return mapMe(updated);
}

// Persist a subset of the user's preferences; returns the full updated set.
export async function savePreferences(patch) {
  return apiSend("/users/me/preferences", "PUT", patch);
}

// ── CRUD mutations (Users / Devices / Species) ────────────────────────────
// Register a new user (public endpoint — needs name+email+password, optional role/phone).
export async function createUser(body) {
  return apiSend("/users", "POST", body);
}

// Update an existing user's editable fields (name/phone/notify/email).
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
