import { describe, it, expect } from "vitest";
import { firstsTable, onlyAt } from "./compare.js";

const FEEDERS = [{ device_id: 1, name: "Home" }, { device_id: 2, name: "Dad's" }];
const SPECIES = [
  { id: 10, common_name: "Jay", palette: [], firsts: [{ device_id: 1, first_seen: "2026-03-02T15:00:00Z" }] },
  { id: 11, common_name: "Wren", palette: [], firsts: [{ device_id: 2, first_seen: "2026-04-10T15:00:00Z" }] },
  {
    id: 12, common_name: "Cardinal", palette: [],
    firsts: [
      { device_id: 2, first_seen: "2026-01-04T15:00:00Z" },
      { device_id: 1, first_seen: "2026-01-09T15:00:00Z" },
    ],
  },
];

describe("onlyAt", () => {
  it("keeps the species one feeder saw and no other", () => {
    expect(onlyAt(SPECIES, 1).map(s => s.common_name)).toEqual(["Jay"]);
    expect(onlyAt(SPECIES, 2).map(s => s.common_name)).toEqual(["Wren"]);
    expect(onlyAt(SPECIES, 3)).toEqual([]);
  });
});

describe("firstsTable", () => {
  it("puts each first visit under its feeder, in feeder order", () => {
    const rows = firstsTable(SPECIES, FEEDERS);
    const cardinal = rows[2];
    expect(cardinal.cells.map(d => d?.toISOString())).toEqual([
      "2026-01-09T15:00:00.000Z", "2026-01-04T15:00:00.000Z",
    ]);
    expect(rows[0].cells[1]).toBeNull();
  });

  it("marks the earliest feeder only when two or more saw it", () => {
    const rows = firstsTable(SPECIES, FEEDERS);
    expect(rows[2].earliest).toBe(2);
    expect(rows[0].earliest).toBeNull();
  });
});
