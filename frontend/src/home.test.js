import { describe, it, expect } from "vitest";
import {
  fmtClock, heroWhen, isUnknown, statusLine, stripLabel, timelinePos, yesterdayBounds, yesterdayLine,
} from "./home.js";

// Fixed reference: Thu 2026-10-29, 7:42 pm local time.
const NOW = new Date(2026, 9, 29, 19, 42);
const at = (h, m, day = 29) => new Date(2026, 9, day, h, m);
const visit = (common, d) => ({ species: { common }, datetime: d });

describe("heroWhen", () => {
  it("says how long ago a visit today came", () => {
    expect(heroWhen(at(19, 31), NOW)).toBe("11 minutes ago · 7:31 pm");
    expect(heroWhen(at(17, 10), NOW)).toBe("2 hours ago · 5:10 pm");
    expect(heroWhen(new Date(NOW - 20000), NOW)).toBe("Just now · 7:41 pm");
  });

  it("names the day for an older visit", () => {
    expect(heroWhen(at(17, 24, 28), NOW)).toBe("Yesterday, 5:24 pm");
    expect(heroWhen(at(8, 5, 26), NOW)).toBe("Mon, Oct 26, 8:05 am");
  });
});

describe("statusLine", () => {
  it("leads with how long the feeder has been quiet", () => {
    const today = [visit("House Finch", at(19, 31)), visit("House Finch", at(19, 29))];
    expect(statusLine(today[0], today, { now: NOW })).toEqual({
      quiet: "Quiet for 11 minutes.",
      count: "2 visits today, all House Finch.",
      warning: null,
    });
  });

  it("names the main species, or counts them", () => {
    const mostly = [
      visit("House Finch", at(19, 31)), visit("House Finch", at(18, 0)), visit("Blue Jay", at(9, 0)),
    ];
    expect(statusLine(mostly[0], mostly, { now: NOW }).count).toBe("3 visits today, mostly House Finch.");
    const mixed = [
      visit("House Finch", at(19, 31)), visit("Blue Jay", at(18, 0)),
      visit("Blue Jay", at(10, 0)), visit("Mourning Dove", at(9, 0)),
    ];
    expect(statusLine(mixed[0], mixed, { now: NOW }).count).toBe("4 visits today, 3 species.");
  });

  it("does not claim a species mix when the window cut the day short", () => {
    const today = Array.from({ length: 100 }, () => visit("House Finch", at(19, 31)));
    expect(statusLine(today[0], today, { now: NOW, capped: true }).count).toBe("100+ visits today.");
  });

  it("says so when nothing came today", () => {
    expect(statusLine(visit("Blue Jay", at(17, 24, 28)), [], { now: NOW }))
      .toEqual({ quiet: null, count: "No visits yet today.", warning: null });
  });

  it("adds the Tier 2 warning, even on a day with no visits", () => {
    expect(statusLine(visit("Blue Jay", at(17, 24, 28)), [], { now: NOW, tier2Down: true }).warning)
      .toBe("The gaming PC has stopped naming birds, so names may be rougher until it is back.");
  });
});

describe("timelinePos", () => {
  it("maps 6 am to 9 pm onto 0 to 100", () => {
    expect(timelinePos(at(6, 0))).toBe(0);
    expect(timelinePos(at(13, 30))).toBe(50);
    expect(timelinePos(at(21, 0))).toBe(100);
  });

  it("leaves out visits outside the day", () => {
    expect(timelinePos(at(5, 59))).toBeNull();
    expect(timelinePos(at(21, 1))).toBeNull();
  });
});

it("fmtClock is lower case", () => {
  expect(fmtClock(at(7, 31))).toBe("7:31 am");
});

it("treats the Unknown species as unnamed", () => {
  expect(isUnknown({ common: "Unknown" })).toBe(true);
  expect(isUnknown({ common: "House Finch" })).toBe(false);
});

describe("stripLabel", () => {
  it("gives today's visits the time and older ones the day", () => {
    expect(stripLabel(at(14, 33), NOW)).toBe("2:33 pm");
    expect(stripLabel(at(17, 24, 28), NOW)).toBe("Yesterday");
    expect(stripLabel(at(8, 5, 27), NOW)).toBe("Tue");
    expect(stripLabel(at(8, 5, 12), NOW)).toBe("Oct 12");
  });
});

describe("yesterdayBounds", () => {
  it("covers the whole local day before today", () => {
    const { start, end } = yesterdayBounds(NOW);
    expect(start).toEqual(new Date(2026, 9, 28));
    expect(end.getTime()).toBe(new Date(2026, 9, 29).getTime() - 1);
  });
});

describe("yesterdayLine", () => {
  const row = (common, count) => ({ common, count });

  it("names the top three species and counts the rest", () => {
    expect(yesterdayLine([
      row("Cardinal", 14), row("Goldfinch", 9), row("Blue Jay", 6), row("Sparrow", 4),
      row("Wren", 3), row("Dove", 2), row("Robin", 1), row("Junco", 1), row("Finch", 1),
    ])).toEqual({
      visits: "41 visits",
      species: "Cardinal 14, Goldfinch 9, Blue Jay 6 and 6 more species.",
    });
  });

  it("lists a short day in full", () => {
    expect(yesterdayLine([row("Cardinal", 1)])).toEqual({ visits: "1 visit", species: "Cardinal 1." });
    expect(yesterdayLine([row("Cardinal", 3), row("Wren", 2)]).species).toBe("Cardinal 3 and Wren 2.");
  });

  it("counts Unknown visits but never names them as a species", () => {
    expect(yesterdayLine([row("Unknown", 5), row("Wren", 2)])).toEqual({ visits: "7 visits", species: "Wren 2." });
    expect(yesterdayLine([row("Unknown", 2)]).species).toBe("None named.");
  });

  it("is null when yesterday had no visits", () => {
    expect(yesterdayLine([])).toBeNull();
  });
});
