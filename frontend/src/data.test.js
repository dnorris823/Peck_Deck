import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the API layer so loadAll runs against fixtures, not the network.
vi.mock("./api.js", () => ({
  apiGet: vi.fn(),
  apiSend: vi.fn(),
}));

import { apiGet, apiSend } from "./api.js";
import {
  loadAll, saveMe, savePreferences, fetchSighting,
  fmtRelative, fmtTime, fmtDateFull,
  confidenceLevel, countToday, toLocalGrid, fmtDayHeading,
  speciesCountsPath,
} from "./data.js";

// Route each apiGet(path) call to a fixture keyed by path.
function routeApiGet(overrides = {}) {
  const base = {
    "/species": [
      { id: 1, common_name: "Northern Cardinal", genus: "Cardinalis", species_name: "cardinalis",
        order_name: "Passeriformes", palette: ["#b8412c"], silhouette: "songbird",
        wiki_url: "https://en.wikipedia.org/wiki/Northern_cardinal", ebird_code: "norcar",
        note: "Bright red." },
      // Sparse species (Pi-created): missing silhouette/wiki → defaults.
      { id: 2, common_name: "Mystery Bird", genus: "Ignotus", species_name: "avis" },
    ],
    [speciesCountsPath()]: [
      { id: 1, common_name: "Northern Cardinal", genus: "Cardinalis", species_name: "cardinalis",
        count: 12, first_seen: "2026-05-01T08:00:00Z" },
    ],
    "/devices": [
      { id: 10, name: "Backyard", city: "Austin", state: "TX",
        feed_type: "Sunflower", status: "online", battery: null, power_source: "mains", signal: "strong",
        last_seen: new Date().toISOString(), today_sightings: 3, week_sightings: 20, all_time_sightings: 1500 },
    ],
    "/users": [
      { id: 100, name: "Dominic Norris", email: "dom@peck.deck", role: "owner",
        notify_email: true },
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
      notify_email: true },
    "/users/me/preferences": { quiet_interval_seconds: 60 },
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
      ebird: "norcar",
    });

    const device = data.DEVICES[0];
    expect(device).toMatchObject({ id: 10, name: "Backyard", feed: "Sunflower", powerSource: "mains", battery: null });
    expect(data.USERS[0]).toMatchObject({ id: 100, name: "Dominic Norris", av: "DN" });
  });

  it("falls back to defaults for species missing presentation fields", async () => {
    routeApiGet();
    const data = await loadAll();
    const sparse = data.SPECIES.find((s) => s.id === 2);
    // An empty palette stays empty, so the accent can fall back to neutral.
    expect(sparse.palette).toEqual([]);
    expect(sparse.silhouette).toBe("songbird");
    expect(sparse.wiki).toBeNull();
    expect(sparse.ebird).toBeNull();
  });

  it("drops sightings whose species or device can't be resolved", async () => {
    routeApiGet();
    const data = await loadAll();
    expect(data.SIGHTINGS).toHaveLength(1);
    expect(data.SIGHTINGS[0].id).toBe(1000);
    expect(data.SIGHTINGS[0].species.common).toBe("Northern Cardinal");
  });

  it("carries the tier trace, the delayed flag and the weather", async () => {
    const trace = [
      { tier: "gpu", outcome: "accepted", confidence: 0.71, threshold: 0.6 },
      { tier: "local", outcome: "not_run", confidence: null, threshold: 0.85 },
    ];
    routeApiGet({
      "/sightings?limit=100": [
        { id: 1000, species_id: 1, device_id: 10, datetime: "2026-07-19T12:00:00Z",
          confidence_score: 0.71, classification_tier_used: "gpu", has_image: true,
          delayed: true, tier_trace: trace, weather_conditions: "4 °C, light snow" },
        { id: 1002, species_id: 1, device_id: 10, datetime: "2026-07-19T11:00:00Z",
          confidence_score: 0.9, classification_tier_used: "gpu", has_image: true,
          delayed: false, tier_trace: null, weather_conditions: null },
      ],
    });
    const data = await loadAll();
    expect(data.SIGHTINGS[0]).toMatchObject({
      delayed: true, tierTrace: trace, weather: "4 °C, light snow",
    });
    expect(data.SIGHTINGS[1]).toMatchObject({ delayed: false, tierTrace: null, weather: null });
  });

  it("clamps heatmap counts into the CSS heat range (0..4)", async () => {
    routeApiGet();
    const data = await loadAll();
    expect(data.HEATMAP).toEqual([[0, 1, 4]]);
  });
});

describe("fetchSighting", () => {
  it("maps one sighting through the same mapper as the list", async () => {
    routeApiGet({
      "/sightings/77": { id: 77, species_id: 1, device_id: 10, datetime: "2026-07-01T12:00:00Z",
        confidence_score: 0.8, classification_tier_used: "gpu", has_image: false,
        delayed: false, tier_trace: null },
    });
    const data = await loadAll();
    const s = await fetchSighting(77, data);
    expect(s).toMatchObject({ id: 77, tier: "gpu", tierTrace: null, hasImage: false });
    expect(s.species.common).toBe("Northern Cardinal");
    expect(s.datetime).toBeInstanceOf(Date);
  });

  it("is null for a sighting whose species was never loaded", async () => {
    routeApiGet({
      "/sightings/78": { id: 78, species_id: 999, device_id: 10, datetime: "2026-07-01T12:00:00Z",
        confidence_score: 0.8, classification_tier_used: "gpu", has_image: false },
    });
    const data = await loadAll();
    expect(await fetchSighting(78, data)).toBeNull();
  });
});

describe("settings mutations", () => {
  it("saveMe PUTs the patch and returns the mapped user", async () => {
    apiSend.mockResolvedValue({ id: 100, name: "New Name", email: "dom@peck.deck",
      role: "owner", notify_email: true });
    const me = await saveMe(100, { name: "New Name" });
    expect(apiSend).toHaveBeenCalledWith("/users/100", "PUT", { name: "New Name" });
    expect(me.name).toBe("New Name");
  });

  it("savePreferences PUTs to the preferences endpoint", async () => {
    apiSend.mockResolvedValue({ quiet_interval_seconds: 120 });
    const prefs = await savePreferences({ quiet_interval_seconds: 120 });
    expect(apiSend).toHaveBeenCalledWith("/users/me/preferences", "PUT", { quiet_interval_seconds: 120 });
    expect(prefs.quiet_interval_seconds).toBe(120);
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

describe("confidenceLevel", () => {
  it("judges each tier against its own threshold", () => {
    // 0.7 clears the GPU tier's 0.60 but not the Pi tier's 0.85.
    expect(confidenceLevel({ tier: "gpu", confidence: 0.7 })).toBe("sure");
    expect(confidenceLevel({ tier: "local", confidence: 0.7 })).toBe("unsure");
    expect(confidenceLevel({ tier: "none", confidence: 0 })).toBe("unsure");
  });
});

describe("local-time helpers", () => {
  it("countToday counts from local midnight", () => {
    const now = new Date(2026, 9, 28, 19, 0);
    const at = (h, day = 28) => ({ datetime: new Date(2026, 9, day, h, 0) });
    expect(countToday([at(16), at(9), at(23, 27)], now)).toBe(2);
  });

  it("toLocalGrid rotates a UTC grid by the zone offset", () => {
    const grid = Array.from({ length: 7 }, () => Array(24).fill(0));
    grid[3][2] = 4; // Thursday 02:00 UTC
    const pdt = toLocalGrid(grid, -7 * 60);
    expect(pdt[2][19]).toBe(4); // Wednesday 19:00 local
    expect(pdt[3][2]).toBe(0);
    // Sunday wraps forward to Monday.
    const wrap = Array.from({ length: 7 }, () => Array(24).fill(0));
    wrap[6][23] = 1;
    expect(toLocalGrid(wrap, 60)[0][0]).toBe(1);
  });

  it("toLocalGrid leaves an unexpected shape alone", () => {
    expect(toLocalGrid([[0, 1, 4]], 60)).toEqual([[0, 1, 4]]);
  });

  it("fmtDayHeading names today and yesterday", () => {
    const now = new Date(2026, 9, 28, 19, 0);
    expect(fmtDayHeading(new Date(2026, 9, 28, 8), now)).toBe("Today");
    expect(fmtDayHeading(new Date(2026, 9, 27, 23), now)).toBe("Yesterday");
    expect(fmtDayHeading(new Date(2026, 9, 26, 12), now)).toMatch(/Oct 26/);
  });
});

describe("loadAll for a viewer", () => {
  // GET /users is owner only. A viewer's load must not fail on it.
  function refuseUsers(status) {
    routeApiGet();
    const routed = apiGet.getMockImplementation();
    apiGet.mockImplementation((path) => (path === "/users"
      ? Promise.reject(Object.assign(new Error(`failed (${status})`), { status }))
      : routed(path)));
  }

  it("loads with no users when GET /users answers 403", async () => {
    refuseUsers(403);
    const data = await loadAll();
    expect(data.USERS).toEqual([]);
    expect(data.ME.id).toBe(100);
  });

  it("still fails on any other GET /users error", async () => {
    refuseUsers(500);
    await expect(loadAll()).rejects.toThrow("failed (500)");
  });
});
