import { describe, it, expect } from "vitest";
import { HISTORY_PAGE, applyHistoryEvent, historyParams, matchesHistory, mergeRows } from "./history.js";

const ALL = { deviceId: null, speciesId: null, from: null, to: null };
const row = (id, datetime, extra = {}) => ({ id, datetime, device_id: 1, species_id: 5, ...extra });

describe("historyParams", () => {
  it("sends the filters as the server's query parameters", () => {
    const from = Date.parse("2026-10-02T10:00:00Z");
    const p = historyParams({ deviceId: 4, speciesId: 9, from, to: null });
    expect(p.get("limit")).toBe(String(HISTORY_PAGE));
    expect(p.get("device_id")).toBe("4");
    expect(p.get("species_id")).toBe("9");
    expect(p.get("from_date")).toBe("2026-10-02T10:00:00.000Z");
    expect(p.has("to_date")).toBe(false);
    expect(p.has("offset")).toBe(false);
  });

  it("leaves out a filter set to all", () => {
    const p = historyParams(ALL);
    expect([...p.keys()]).toEqual(["limit"]);
  });

  it("ends a one-day range just before the next midnight, since to_date is inclusive", () => {
    const to = Date.parse("2026-10-29T07:00:00Z");
    const p = historyParams({ ...ALL, from: to - 86_400_000, to });
    expect(p.get("to_date")).toBe("2026-10-29T06:59:59.999Z");
  });

  it("starts the next page at the oldest loaded row, skipping the rows held at that time", () => {
    const loaded = [
      row(30, "2026-10-30T09:00:00.000123+00:00"),
      row(29, "2026-10-29T08:00:00.000456+00:00"),
      row(28, "2026-10-29T08:00:00.000456+00:00"),
    ];
    const p = historyParams({ ...ALL, to: Date.parse("2026-10-31T00:00:00Z") }, loaded);
    // The raw string keeps the microseconds a Date would round away.
    expect(p.get("to_date")).toBe("2026-10-29T08:00:00.000456+00:00");
    expect(p.get("offset")).toBe("2");
  });
});

describe("matchesHistory", () => {
  it("checks feeder, species and the time range, with `to` exclusive", () => {
    const at = "2026-10-20T12:00:00Z";
    const t = Date.parse(at);
    expect(matchesHistory(ALL, row(1, at))).toBe(true);
    expect(matchesHistory({ ...ALL, deviceId: 2 }, row(1, at))).toBe(false);
    expect(matchesHistory({ ...ALL, speciesId: 5 }, row(1, at))).toBe(true);
    expect(matchesHistory({ ...ALL, from: t + 1 }, row(1, at))).toBe(false);
    expect(matchesHistory({ ...ALL, to: t }, row(1, at))).toBe(false);
  });
});

describe("mergeRows", () => {
  it("adds only new rows and keeps newest first", () => {
    const rows = [row(3, "2026-10-30T09:00:00Z"), row(1, "2026-10-28T09:00:00Z")];
    const merged = mergeRows(rows, [row(1, "2026-10-28T09:00:00Z"), row(2, "2026-10-29T09:00:00Z")]);
    expect(merged.map((s) => s.id)).toEqual([3, 2, 1]);
    expect(mergeRows(rows, [row(3, "2026-10-30T09:00:00Z")])).toBe(rows);
  });
});

describe("applyHistoryEvent", () => {
  const list = {
    rows: [row(3, "2026-10-30T09:00:00Z"), row(2, "2026-10-29T09:00:00Z")],
    done: false,
  };

  it("puts a matching new sighting at the top", () => {
    const next = applyHistoryEvent(list, { type: "sighting", sighting: row(4, "2026-10-31T09:00:00Z") }, ALL);
    expect(next.rows.map((s) => s.id)).toEqual([4, 3, 2]);
  });

  it("skips a sighting the filters leave out", () => {
    const other = row(4, "2026-10-31T09:00:00Z", { species_id: 6 });
    expect(applyHistoryEvent(list, { type: "sighting", sighting: other }, { ...ALL, speciesId: 5 })).toBe(list);
  });

  it("leaves a backdated sighting older than the loaded pages to the next page", () => {
    const old = row(4, "2026-10-01T09:00:00Z");
    expect(applyHistoryEvent(list, { type: "sighting", sighting: old }, ALL)).toBe(list);
    const all = applyHistoryEvent({ ...list, done: true }, { type: "sighting", sighting: old }, ALL);
    expect(all.rows.map((s) => s.id)).toEqual([3, 2, 4]);
  });

  it("drops a deleted sighting and swaps in an updated one", () => {
    expect(applyHistoryEvent(list, { type: "deleted", id: 3 }, ALL).rows.map((s) => s.id)).toEqual([2]);
    const fixed = { ...list.rows[1], species_id: 7 };
    expect(applyHistoryEvent(list, { type: "updated", sighting: fixed }, ALL).rows[1].species_id).toBe(7);
    expect(applyHistoryEvent(list, { type: "deleted", id: 99 }, ALL)).toBe(list);
  });
});
