import { describe, it, expect } from "vitest";
import { rangeCutoff } from "./Sightings.jsx";

// Fixed reference: 2026-07-19 15:30 local time.
const NOW = new Date(2026, 6, 19, 15, 30, 0).getTime();
const DAY = 24 * 60 * 60 * 1000;

describe("rangeCutoff", () => {
  it("returns 0 (no lower bound) for all time", () => {
    expect(rangeCutoff("all", NOW)).toBe(0);
    expect(rangeCutoff("anything-unknown", NOW)).toBe(0);
  });

  it("today is midnight of the current day", () => {
    const cutoff = new Date(rangeCutoff("today", NOW));
    expect(cutoff.getHours()).toBe(0);
    expect(cutoff.getMinutes()).toBe(0);
    expect(cutoff.getDate()).toBe(19);
    // Something captured at 15:30 today is included; 23:59 yesterday is not.
    expect(NOW).toBeGreaterThanOrEqual(cutoff.getTime());
    expect(new Date(2026, 6, 18, 23, 59).getTime()).toBeLessThan(cutoff.getTime());
  });

  it("week is 7 days back, month is 30 days back", () => {
    expect(rangeCutoff("week", NOW)).toBe(NOW - 7 * DAY);
    expect(rangeCutoff("month", NOW)).toBe(NOW - 30 * DAY);
  });

  it("orders the windows from narrowest to widest", () => {
    const today = rangeCutoff("today", NOW);
    const week = rangeCutoff("week", NOW);
    const month = rangeCutoff("month", NOW);
    const all = rangeCutoff("all", NOW);
    expect(today).toBeGreaterThan(week);
    expect(week).toBeGreaterThan(month);
    expect(month).toBeGreaterThan(all);
  });
});
