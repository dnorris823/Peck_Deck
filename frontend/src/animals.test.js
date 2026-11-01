import { describe, it, expect } from "vitest";
import { afterDays, birdLine, dayIndex, groupLabel, measureLine, stackDays } from "./animals.js";

const BAFFLE = { name: "Baffle on the pole" };
const DONE = { after_start: "2026-10-01T12:00:00Z", after_end: "2026-10-15T12:00:00Z", complete: true };

describe("measureLine", () => {
  it("reads the way the issue writes it", () => {
    const rr = { before: 100, after: 28, ratio: 0.28, low: 0.17, high: 0.45 };
    expect(measureLine("squirrel", rr, BAFFLE, DONE)).toBe(
      "Squirrel visits down 72% (95% interval 55% to 83%) in the 14 days after Baffle on the pole");
  });

  it("names each direction when the interval crosses no change", () => {
    const rr = { before: 20, after: 18, ratio: 0.9, low: 0.6, high: 1.3 };
    expect(measureLine("raccoon", rr, BAFFLE, DONE)).toBe(
      "Raccoon visits down 10% (95% interval down 40% to up 30%) in the 14 days after Baffle on the pole");
  });

  it("says up for a rise", () => {
    const rr = { before: 10, after: 20, ratio: 2, low: 1.2, high: 3.4 };
    expect(measureLine("cat", rr, BAFFLE, DONE)).toMatch(/^Cat visits up 100% \(95% interval 20% to 240%\)/);
  });

  it("says so far while the after window is still filling", () => {
    const rr = { before: 10, after: 3, ratio: 0.5, low: 0.2, high: 0.9 };
    const open = { after_start: "2026-10-01T12:00:00Z", after_end: "2026-10-04T12:00:00Z", complete: false };
    expect(measureLine("squirrel", rr, BAFFLE, open)).toMatch(/in the 3 days so far after Baffle on the pole$/);
  });

  it("handles zero counts without an interval", () => {
    expect(measureLine("squirrel", { before: 40, after: 0, ratio: 0, low: null, high: null }, BAFFLE, DONE))
      .toBe("No squirrel visits in the 14 days after Baffle on the pole, against 40 before.");
    expect(measureLine("deer", { before: 0, after: 4, ratio: null, low: null, high: null }, BAFFLE, DONE))
      .toBe("No deer visits in the 14 days before Baffle on the pole, so nothing to compare.");
  });

  it("never says because", () => {
    const rr = { before: 100, after: 28, ratio: 0.28, low: 0.17, high: 0.45 };
    expect(measureLine("squirrel", rr, BAFFLE, DONE)).not.toMatch(/because/i);
  });
});

describe("helpers", () => {
  it("puts the bird line beside the animals", () => {
    expect(birdLine({ ratio: 0.95 })).toBe("Birds down 5% over the same days.");
    expect(birdLine({ ratio: null })).toMatch(/Too few bird visits/);
  });

  it("counts whole days in the after window", () => {
    expect(afterDays(DONE)).toBe(14);
  });

  it("labels an unknown group", () => {
    expect(groupLabel("squirrel")).toBe("Squirrel");
    expect(groupLabel("weasel")).toBe("Weasel");
  });

  it("stacks each day's groups from the bottom", () => {
    const days = [
      { date: "2026-10-01", animals: { squirrel: 3, raccoon: 1 }, birds: 9 },
      { date: "2026-10-02", animals: {}, birds: 4 },
    ];
    const [one, two] = stackDays(days, ["squirrel", "raccoon"]);
    expect(one.segments).toEqual([
      { group: "squirrel", from: 0, to: 3 },
      { group: "raccoon", from: 3, to: 4 },
    ]);
    expect(one.total).toBe(4);
    expect(two.segments).toEqual([]);
  });

  it("finds the local day of a measure", () => {
    const days = [{ date: "2026-10-20" }, { date: "2026-10-21" }];
    expect(dayIndex(days, "2026-10-21T02:00:00Z", "America/Los_Angeles")).toBe(0);
    expect(dayIndex(days, "2026-10-21T02:00:00Z", "UTC")).toBe(1);
    expect(dayIndex(days, "2026-11-30T02:00:00Z", "UTC")).toBeNull();
  });
});
