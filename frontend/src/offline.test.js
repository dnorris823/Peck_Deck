import { describe, it, expect, beforeEach, vi } from "vitest";
import { clearSnapshot, loadSnapshot, saveSnapshot } from "./offline.js";

const KEY = "peckdeck_snapshot";
const DAY = 24 * 60 * 60 * 1000;

beforeEach(() => clearSnapshot());

describe("offline snapshot", () => {
  it("round-trips raw payloads", () => {
    expect(saveSnapshot({ species: [{ id: 1 }] }, 1000)).toBe(true);
    expect(loadSnapshot(2000)).toEqual({ raw: { species: [{ id: 1 }] }, savedAt: 1000 });
  });

  it("returns null when nothing is stored", () => {
    expect(loadSnapshot()).toBeNull();
  });

  it("drops a snapshot older than a week", () => {
    saveSnapshot({ species: [] }, 0);
    // Week-old feeder status presented as current is worse than no content.
    expect(loadSnapshot(8 * DAY)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("keeps a snapshot inside the freshness window", () => {
    saveSnapshot({ species: [] }, 0);
    expect(loadSnapshot(6 * DAY)).not.toBeNull();
  });

  it("discards an entry written by an older schema", () => {
    localStorage.setItem(KEY, JSON.stringify({ schema: 0, savedAt: Date.now(), raw: {} }));
    expect(loadSnapshot()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("discards a corrupt entry instead of throwing", () => {
    localStorage.setItem(KEY, "{not json");
    expect(loadSnapshot()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("discards an entry with no timestamp", () => {
    localStorage.setItem(KEY, JSON.stringify({ schema: 1, raw: {} }));
    expect(loadSnapshot()).toBeNull();
  });

  it("reports failure rather than throwing when storage rejects the write", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    try {
      // A full quota must degrade the offline feature, not break loading.
      expect(saveSnapshot({ species: [] })).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });
});
