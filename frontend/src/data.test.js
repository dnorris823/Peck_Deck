import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the API layer so loadAll runs against fixtures, not the network.
vi.mock("./api.js", () => ({
  apiGet: vi.fn(),
  apiSend: vi.fn(),
}));

import { apiGet, apiSend } from "./api.js";
import {
  loadAll, saveMe, savePreferences,
  fmtRelative, fmtTime, fmtDateFull,
} from "./data.js";

// Route each apiGet(path) call to a fixture keyed by path.
function routeApiGet(overrides = {}) {
  const base = {
    "/species": [
      { id: 1, common_name: "Northern Cardinal", genus: "Cardinalis", species_name: "cardinalis",
        order_name: "Passeriformes", palette: ["#b8412c"], silhouette: "songbird",
        wiki_url: "https://en.wikipedia.org/wiki/Northern_cardinal", note: "Bright red." },
      // Sparse species (Pi-created): missing palette/silhouette/wiki → defaults.
      { id: 2, common_name: "Mystery Bird", genus: "Ignotus", species_name: "avis" },
    ],
    "/stats/species-counts": [
      { id: 1, common_name: "Northern Cardinal", genus: "Cardinalis", species_name: "cardinalis",
        count: 12, first_seen: "2026-05-01T08:00:00Z" },
    ],
    "/devices": [
      { id: 10, name: "Backyard", city: "Austin", state: "TX", classification_tier: "auto",
        feed_type: "Sunflower", status: "online", battery: 88, signal: "strong",
        last_seen: new Date().toISOString(), today_sightings: 3, week_sightings: 20, all_time_sightings: 1500 },
    ],
    "/users": [
      { id: 100, name: "Dominic Norris", email: "dom@peck.deck", role: "owner",
        phone: "+15125550100", notify_email: true, notify_sms: false },
    ],
    "/sightings?limit=100": [
      // Valid: species + device both resolve.
      { id: 1000, species_id: 1, device_id: 10, datetime: "2026-07-19T12:00:00Z",
        confidence_score: 0.95, classification_tier_used: "cloud", has_image: true },
      // Orphan: species_id has no match → filtered out.
      { id: 1001, species_id: 999, device_id: 10, datetime: "2026-07-19T12:05:00Z",
        confidence_score: 0.7, classification_tier_used: "local", has_image: false },
    ],
    "/stats/heatmap": [[0, 1, 9]], // 9 clamped to 4
    "/stats/dashboard": { today_sightings: 3, total_species: 2 },
    "/users/me": { id: 100, name: "Dominic Norris", email: "dom@peck.deck", role: "owner",
      phone: "+15125550100", notify_email: true, notify_sms: false },
    "/users/me/preferences": { default_tier: "auto", escalation_threshold: 70, quiet_interval_seconds: 60 },
  };
  const table = { ...base, ...overrides };
  apiGet.mockImplementation((path) => {
    if (!(path in table)) throw new Error(`unexpected apiGet path: ${path}`);
    return Promise.resolve(table[path]);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("loadAll", () => {
  it("maps snake_case backend rows into the camelCase UI shape", async () => {
    routeApiGet();
    const data = await loadAll();

    const cardinal = data.SPECIES.find((s) => s.id === 1);
    expect(cardinal).toMatchObject({
      common: "Northern Cardinal",
      sci: "Cardinalis cardinalis",
      order: "Passeriformes",
      wiki: "https://en.wikipedia.org/wiki/Northern_cardinal",
    });

    const device = data.DEVICES[0];
    expect(device).toMatchObject({ id: 10, name: "Backyard", tier: "auto", feed: "Sunflower" });
    expect(data.USERS[0]).toMatchObject({ id: 100, name: "Dominic Norris", av: "DN" });
  });

  it("falls back to defaults for species missing presentation fields", async () => {
    routeApiGet();
    const data = await loadAll();
    const sparse = data.SPECIES.find((s) => s.id === 2);
    expect(sparse.palette.length).toBeGreaterThan(0);
    expect(sparse.silhouette).toBe("songbird");
    expect(sparse.wiki).toBeNull();
  });

  it("drops sightings whose species or device can't be resolved", async () => {
    routeApiGet();
    const data = await loadAll();
    expect(data.SIGHTINGS).toHaveLength(1);
    expect(data.SIGHTINGS[0].id).toBe(1000);
    expect(data.SIGHTINGS[0].species.common).toBe("Northern Cardinal");
  });

  it("clamps heatmap counts into the CSS heat range (0..4)", async () => {
    routeApiGet();
    const data = await loadAll();
    expect(data.HEATMAP).toEqual([[0, 1, 4]]);
  });
});

describe("settings mutations", () => {
  it("saveMe PUTs the patch and returns the mapped user", async () => {
    apiSend.mockResolvedValue({ id: 100, name: "New Name", email: "dom@peck.deck",
      role: "owner", phone: "", notify_email: true, notify_sms: false });
    const me = await saveMe(100, { name: "New Name" });
    expect(apiSend).toHaveBeenCalledWith("/users/100", "PUT", { name: "New Name" });
    expect(me.name).toBe("New Name");
  });

  it("savePreferences PUTs to the preferences endpoint", async () => {
    apiSend.mockResolvedValue({ default_tier: "cloud" });
    const prefs = await savePreferences({ default_tier: "cloud" });
    expect(apiSend).toHaveBeenCalledWith("/users/me/preferences", "PUT", { default_tier: "cloud" });
    expect(prefs.default_tier).toBe("cloud");
  });
});

describe("date/time formatters", () => {
  it("fmtRelative describes minutes/hours/days ago", () => {
    const now = Date.now();
    expect(fmtRelative(new Date(now - 30 * 1000))).toBe("just now");
    expect(fmtRelative(new Date(now - 5 * 60 * 1000))).toBe("5m ago");
    expect(fmtRelative(new Date(now - 3 * 60 * 60 * 1000))).toBe("3h ago");
    expect(fmtRelative(new Date(now - 2 * 24 * 60 * 60 * 1000))).toBe("2d ago");
  });

  it("fmtTime and fmtDateFull produce non-empty strings", () => {
    const d = new Date("2026-07-19T15:30:00Z");
    expect(typeof fmtTime(d)).toBe("string");
    expect(fmtTime(d).length).toBeGreaterThan(0);
    expect(fmtDateFull(d)).toMatch(/2026/);
  });
});
