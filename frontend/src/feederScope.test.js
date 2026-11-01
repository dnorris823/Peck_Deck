import { describe, it, expect, beforeEach } from "vitest";
import { SCOPE_KEY, readScope, saveScope, validScope, withScope } from "./feederScope.js";

beforeEach(() => localStorage.clear());

describe("feeder scope", () => {
  it("keeps the choice in the browser, and clears it for all feeders", () => {
    expect(readScope()).toBe(null);
    saveScope(7);
    expect(localStorage.getItem(SCOPE_KEY)).toBe("7");
    expect(readScope()).toBe(7);
    saveScope(null);
    expect(readScope()).toBe(null);
  });

  it("reads junk in storage as all feeders", () => {
    localStorage.setItem(SCOPE_KEY, "porch");
    expect(readScope()).toBe(null);
  });

  it("falls back to all feeders when the saved one is gone", () => {
    const devices = [{ id: 1 }, { id: 2 }];
    expect(validScope(2, devices)).toBe(2);
    expect(validScope(9, devices)).toBe(null);
    expect(validScope(null, devices)).toBe(null);
    expect(validScope(2, undefined)).toBe(null);
  });

  it("adds device_id only for one feeder", () => {
    expect(withScope("/stats/heatmap", null)).toBe("/stats/heatmap");
    expect(withScope("/stats/heatmap", 4)).toBe("/stats/heatmap?device_id=4");
    expect(withScope("/stats/species-counts?tz=UTC", 4)).toBe("/stats/species-counts?tz=UTC&device_id=4");
  });
});
