import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./api.js", () => ({ apiGet: vi.fn() }));

import { apiGet } from "./api.js";
import {
  fetchHours, fmtClock, fmtHour, fmtSeen, fmtVisit, isUnknown, speciesLinks, usualTime,
} from "./speciesData.js";

// Fixed reference: Wed 2026-10-28 19:42 local time.
const NOW = new Date(2026, 9, 28, 19, 42);

beforeEach(() => vi.clearAllMocks());

describe("fetchHours", () => {
  it("sends the species, the period and the time zone", async () => {
    apiGet.mockResolvedValue({ counts: [] });
    await fetchHours(7, { days: 30, zone: "America/Los_Angeles" });
    expect(apiGet).toHaveBeenCalledWith("/stats/hours?species_id=7&days=30&tz=America%2FLos_Angeles");
  });

  it("asks for all time with days=0", async () => {
    apiGet.mockResolvedValue({ counts: [] });
    await fetchHours(7, { days: 0, zone: "UTC" });
    expect(apiGet.mock.calls[0][0]).toContain("days=0");
  });

  it("defaults to the browser's own zone", async () => {
    apiGet.mockResolvedValue({ counts: [] });
    await fetchHours(7);
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(apiGet.mock.calls[0][0]).toContain(`tz=${encodeURIComponent(zone)}`);
  });
});

describe("hour labels", () => {
  it("reads hours the way people say them", () => {
    expect(fmtHour(0)).toBe("12 am");
    expect(fmtHour(8)).toBe("8 am");
    expect(fmtHour(12)).toBe("noon");
    expect(fmtHour(17)).toBe("5 pm");
  });

  it("turns HH:MM into a 12-hour clock", () => {
    expect(fmtClock("05:20")).toBe("5:20 am");
    expect(fmtClock("00:07")).toBe("12:07 am");
    expect(fmtClock("12:30")).toBe("12:30 pm");
    expect(fmtClock("19:58")).toBe("7:58 pm");
    expect(fmtClock(null)).toBeNull();
  });
});

describe("usualTime", () => {
  it("names the part of the day for one peak", () => {
    expect(usualTime([8])).toBe("mornings");
    expect(usualTime([18])).toBe("evenings");
    expect(usualTime([12])).toBe("midday");
    expect(usualTime([2])).toBe("nights");
  });

  it("keeps two peaks in one part of the day as that part", () => {
    expect(usualTime([7, 9])).toBe("mornings");
  });

  it("lists two separate peaks in clock order", () => {
    expect(usualTime([17, 8])).toBe("8 am, 5 pm");
  });

  it("says nothing without peaks", () => {
    expect(usualTime([])).toBeNull();
    expect(usualTime(null)).toBeNull();
  });
});

describe("fmtSeen", () => {
  it("counts minutes inside the hour", () => {
    expect(fmtSeen(new Date(2026, 9, 28, 19, 31), NOW)).toBe("11 min ago");
  });

  it("gives today's time, then the day", () => {
    expect(fmtSeen(new Date(2026, 9, 28, 14, 33), NOW)).toBe("today 2:33 pm");
    expect(fmtSeen(new Date(2026, 9, 27, 23, 50), NOW)).toBe("yesterday");
    expect(fmtSeen(new Date(2026, 9, 25, 9, 0), NOW)).toBe("Sun");
    expect(fmtSeen(new Date(2026, 9, 12, 9, 0), NOW)).toBe("Oct 12");
    expect(fmtSeen(new Date(2025, 9, 12, 9, 0), NOW)).toBe("Oct 12, 2025");
  });

  it("has a short form for the stat row", () => {
    expect(fmtSeen(new Date(2026, 9, 28, 14, 33), NOW, { short: true })).toBe("Today");
    expect(fmtSeen(new Date(2026, 9, 27, 9, 0), NOW, { short: true })).toBe("Yesterday");
  });
});

describe("fmtVisit", () => {
  it("shows the time today and the day before that", () => {
    expect(fmtVisit(new Date(2026, 9, 28, 17, 24), NOW)).toBe("5:24 pm");
    expect(fmtVisit(new Date(2026, 9, 27, 17, 24), NOW)).toBe("Yesterday");
    expect(fmtVisit(new Date(2026, 9, 25, 18, 2), NOW)).toBe("Sun");
  });
});

describe("isUnknown", () => {
  it("matches the species the Pi files unnamed captures under", () => {
    expect(isUnknown({ common: "Unknown" })).toBe(true);
    expect(isUnknown({ common: " unknown " })).toBe(true);
    expect(isUnknown({ common: "House Finch" })).toBe(false);
  });
});

describe("speciesLinks", () => {
  const labels = (s) => speciesLinks(s).map((l) => l.label);

  it("skips eBird and All About Birds without an eBird code", () => {
    expect(labels({ common: "Made Up Finch", wiki: null, ebird: null })).toEqual(["Xeno-canto"]);
  });

  it("gives an Unknown capture no links", () => {
    expect(speciesLinks({ common: "Unknown", wiki: null, ebird: null })).toEqual([]);
  });

  it("escapes the common name in the Xeno-canto search", () => {
    const [xc] = speciesLinks({ common: "Cooper's Hawk", wiki: null, ebird: null });
    expect(xc.href).toBe("https://xeno-canto.org/explore?query=Cooper's%20Hawk");
  });
});
