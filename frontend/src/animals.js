// The Animals view's words and numbers, kept out of the component so tests can
// read them. The backend's GET /stats/animals does the counting.

// Every group the backend knows, in the order Settings lists them. Colours are
// fixed per group, so a squirrel is the same colour on every chart.
export const GROUPS = [
  { id: "squirrel", label: "Squirrel", color: "#a6533d" },
  { id: "raccoon", label: "Raccoon", color: "#3f6e89" },
  { id: "bear", label: "Bear", color: "#56663a" },
  { id: "cat", label: "Cat", color: "#86641d" },
  { id: "chipmunk", label: "Chipmunk", color: "#6b4570" },
  { id: "rat", label: "Rat", color: "#5d5d5d" },
  { id: "rabbit", label: "Rabbit", color: "#b07a4f" },
  { id: "opossum", label: "Opossum", color: "#8a8f99" },
  { id: "deer", label: "Deer", color: "#4f7d6b" },
];

const BY_ID = new Map(GROUPS.map(g => [g.id, g]));

export function groupLabel(id) {
  return BY_ID.get(id)?.label || (id ? id[0].toUpperCase() + id.slice(1) : "Animal");
}

export function groupColor(id) {
  return BY_ID.get(id)?.color || "#777";
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days in the after window, at least 1. */
export function afterDays(effect) {
  const ms = new Date(effect.after_end) - new Date(effect.after_start);
  return Math.max(1, Math.round(ms / DAY_MS));
}

// A ratio as a change: 0.28 is "down 72%", 1.3 is "up 30%".
function change(ratio) {
  const pct = Math.round(Math.abs(1 - ratio) * 100);
  if (pct === 0) return "no change";
  return ratio < 1 ? `down ${pct}%` : `up ${pct}%`;
}

/**
 * The interval in the same words as the change. Both bounds below 1 read as
 * "55% to 83%", the way the issue writes it. Bounds either side of 1 name the
 * direction of each.
 */
function interval(low, high) {
  if (high < 1) return `${Math.round((1 - high) * 100)}% to ${Math.round((1 - low) * 100)}%`;
  if (low > 1) return `${Math.round((low - 1) * 100)}% to ${Math.round((high - 1) * 100)}%`;
  return `${change(low)} to ${change(high)}`;
}

/**
 * One card line for one group, such as
 * "Squirrel visits down 72% (95% interval 55% to 83%) in the 14 days after
 * Baffle on the pole". It says "after", never "because of": one feeder has no
 * control group.
 */
export function measureLine(group, rr, measure, effect) {
  const days = afterDays(effect);
  const span = effect.complete ? `in the ${days} days after` : `in the ${days} days so far after`;
  const what = `${groupLabel(group)} visits`;
  if (rr.ratio == null) {
    if (rr.before === 0) return `No ${groupLabel(group).toLowerCase()} visits in the 14 days before ${measure.name}, so nothing to compare.`;
    return `${what}: not enough camera time to compare around ${measure.name}.`;
  }
  if (rr.after === 0) return `No ${groupLabel(group).toLowerCase()} visits ${span} ${measure.name}, against ${rr.before} before.`;
  const ci = rr.low != null && rr.high != null ? ` (95% interval ${interval(rr.low, rr.high)})` : "";
  return `${what} ${change(rr.ratio)}${ci} ${span} ${measure.name}`;
}

/** The bird line beside it, so a drop for weather or empty feed shows. */
export function birdLine(rr) {
  if (rr.ratio == null) return "Too few bird visits to compare over the same days.";
  return `Birds ${change(rr.ratio)} over the same days.`;
}

/**
 * The stacked bars: one entry per day, with each group's segment from the
 * bottom up. Groups stack in the order given, most visits first.
 */
export function stackDays(days, groups) {
  return days.map(d => {
    let y = 0;
    const segments = groups.map(g => {
      const n = d.animals[g] || 0;
      const seg = { group: g, from: y, to: y + n };
      y += n;
      return seg;
    }).filter(s => s.to > s.from);
    return { date: d.date, total: y, birds: d.birds, segments };
  });
}

/** Where a timestamp falls among the days, as a fractional day index, or null. */
export function dayIndex(days, iso, zone) {
  if (!days.length || !iso) return null;
  const local = new Date(iso).toLocaleDateString("en-CA", { timeZone: zone });
  const i = days.findIndex(d => d.date === local);
  return i < 0 ? null : i;
}
