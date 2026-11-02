// Compare page helpers: which species only one feeder saw, and the first of
// the year table. The rows come from GET /stats/compare.

/** The species seen this year at `deviceId` and at no other feeder. */
export function onlyAt(species, deviceId) {
  return species.filter((s) => s.firsts.length === 1 && s.firsts[0].device_id === deviceId);
}

/**
 * One row per species for the first of the year table. `cells` follows the
 * order of `feeders`, with null where that feeder has not seen it this year.
 * `earliest` is the feeder that saw it first, or null when only one did.
 */
export function firstsTable(species, feeders) {
  return species.map((s) => {
    const byFeeder = new Map(s.firsts.map((f) => [f.device_id, new Date(f.first_seen)]));
    return {
      species: s,
      cells: feeders.map((f) => byFeeder.get(f.device_id) || null),
      earliest: s.firsts.length > 1 ? s.firsts[0].device_id : null,
    };
  });
}

/** "Mar 14", in the viewer's zone. */
export function fmtFirst(d) {
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
