// Home's wording and the day timeline. Kept apart from Dashboard.jsx so the
// sentences can be tested against a fixed clock.
import { startOfToday } from "./data.js";

// The timeline covers 6 am to 9 pm, the hours a feeder sees birds.
export const DAY_START_HOUR = 6;
export const DAY_END_HOUR = 21;

const MINUTE = 60000;
const HOUR = 60 * MINUTE;

/** "7:31 pm", the mockups' lower-case clock. */
export function fmtClock(d) {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "11 minutes" or "3 hours". Whole units, rounded down. */
function span(ms) {
  if (ms < HOUR) return plural(Math.max(1, Math.floor(ms / MINUTE)), "minute");
  return plural(Math.floor(ms / HOUR), "hour");
}

export function isToday(d, now = new Date()) {
  return d.getTime() >= startOfToday(now).getTime();
}

/**
 * When the hero bird came. Today it says how long ago: "11 minutes ago · 7:31 pm".
 * On a quiet morning the hero shows an older bird, and the line names the day
 * plainly, so nobody reads yesterday's finch as this morning's.
 */
export function heroWhen(d, now = new Date()) {
  if (isToday(d, now)) {
    const ago = now - d < MINUTE ? "Just now" : `${span(now - d)} ago`;
    return `${ago} · ${fmtClock(d)}`;
  }
  const days = Math.round((startOfToday(now) - startOfToday(d)) / (24 * HOUR));
  const day = days === 1
    ? "Yesterday"
    : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day}, ${fmtClock(d)}`;
}

/** The species Home treats as unnamed. The Pi uploads this when every tier fails. */
export function isUnknown(species) {
  return !species || species.common.trim().toLowerCase() === "unknown";
}

// Home's one sentence for a feeder whose Tier 2 stopped answering. No counts and
// no tier names: the Feeders page has those.
export const TIER2_DOWN = "The gaming PC has stopped naming birds, so names may be rougher until it is back.";

/**
 * The status line under the hero: the bold quiet span, the day's count, and a
 * warning that is null unless `tier2Down`. `capped` means every loaded sighting
 * is from today, so the true count may be higher than the list holds.
 */
export function statusLine(latest, today, { now = new Date(), capped = false, tier2Down = false } = {}) {
  return { ...dayLine(latest, today, now, capped), warning: tier2Down ? TIER2_DOWN : null };
}

function dayLine(latest, today, now, capped) {
  if (today.length === 0) return { quiet: null, count: "No visits yet today." };

  const quiet = now - latest.datetime < MINUTE
    ? "A visit just now."
    : `Quiet for ${span(now - latest.datetime)}.`;

  const n = today.length;
  if (capped) return { quiet, count: `${n}+ visits today.` };
  if (n === 1) return { quiet, count: "1 visit today." };

  const bySpecies = new Map();
  for (const s of today) bySpecies.set(s.species.common, (bySpecies.get(s.species.common) || 0) + 1);
  const [[top, topCount]] = [...bySpecies].sort((a, b) => b[1] - a[1]);
  let who;
  if (bySpecies.size === 1) who = `all ${top}`;
  else if (topCount * 2 > n) who = `mostly ${top}`;
  else who = `${bySpecies.size} species`;
  return { quiet, count: `${n} visits today, ${who}.` };
}

/** Where a time sits on the timeline, 0 to 100, or null outside 6 am to 9 pm. */
export function timelinePos(d) {
  const hours = d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
  if (hours < DAY_START_HOUR || hours > DAY_END_HOUR) return null;
  return ((hours - DAY_START_HOUR) / (DAY_END_HOUR - DAY_START_HOUR)) * 100;
}

// Below this many visits today, the strip shows the latest visits from any day.
export const RECENT_BELOW = 4;
export const RECENT_COUNT = 8;

/** The local day before `now`, as inclusive bounds for a date-range query. */
export function yesterdayBounds(now = new Date()) {
  const today = startOfToday(now);
  // Built from the date parts, so a day with a clock change still ends at midnight.
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  return { start, end: new Date(today.getTime() - 1) };
}

/**
 * A recent visit's label in the strip. Today's say the time. Older ones say the
 * day: "Yesterday", "Tue", or "Oct 12" past a week.
 */
export function stripLabel(d, now = new Date()) {
  if (isToday(d, now)) return fmtClock(d);
  const days = Math.round((startOfToday(now) - startOfToday(d)) / (24 * HOUR));
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString("en-US", { weekday: "short" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const NAMED_IN_LINE = 3;

/**
 * Yesterday's line from per-species counts, `[{ common, count }]` most frequent
 * first. Null when yesterday had no visits. Unknown visits count toward the total
 * but are not a species, so the line never names them.
 */
export function yesterdayLine(rows) {
  const total = rows.reduce((n, r) => n + r.count, 0);
  if (total === 0) return null;
  const named = rows
    .filter(r => !isUnknown(r))
    .sort((a, b) => b.count - a.count || a.common.localeCompare(b.common));
  const shown = named.slice(0, NAMED_IN_LINE).map(r => `${r.common} ${r.count}`);
  const more = named.length - shown.length;
  let species;
  if (shown.length === 0) species = "None named.";
  else if (more > 0) species = `${shown.join(", ")} and ${more} more species.`;
  else if (shown.length === 1) species = `${shown[0]}.`;
  else species = `${shown.slice(0, -1).join(", ")} and ${shown[shown.length - 1]}.`;
  return { visits: plural(total, "visit"), species };
}
