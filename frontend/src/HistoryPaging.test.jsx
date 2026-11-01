// History pages through the server, not through Home's newest 100.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

let mockData;
let listener = null;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({
    data: mockData,
    reload: vi.fn(),
    subscribe: (fn) => { listener = fn; return () => { listener = null; }; },
  }),
}));
vi.mock("./SightingImage.jsx", () => ({ SightingImage: () => null }));
vi.mock("./api.js", async (importOriginal) => ({ ...(await importOriginal()), apiGet: vi.fn() }));

import { Sightings } from "./Sightings.jsx";
import { apiGet } from "./api.js";
import { HISTORY_PAGE } from "./history.js";

const DAY = 86_400_000;
const feeder = { id: 1, name: "Maple", ownerId: 2 };
const sparrow = { id: 5, common: "House Sparrow", palette: [], silhouette: "songbird" };
const siskin = { id: 6, common: "Pine Siskin", palette: [], silhouette: "songbird" };

// 500 sparrow visits spread over the last 30 days, plus one Pine Siskin 25
// days ago. Home's newest 100 reach back about 6 days.
function seed(now) {
  const step = (30 * DAY - 3_600_000) / 500;
  const rows = Array.from({ length: 500 }, (_, i) => ({
    id: 1000 - i, device_id: 1, species_id: sparrow.id, classification_tier_used: "gpu",
    confidence_score: 0.9, has_image: true,
    datetime: new Date(now - i * step).toISOString(),
  }));
  rows.push({
    id: 1, device_id: 1, species_id: siskin.id, classification_tier_used: "gpu",
    confidence_score: 0.9, has_image: true,
    datetime: new Date(now - 25 * DAY).toISOString(),
  });
  return rows;
}

// GET /sightings as the backend answers it: filtered, newest first, ties by
// id, to_date inclusive, at most 100 rows.
function serve(rows) {
  return async (path) => {
    const url = new URL(path, "http://x");
    const q = url.searchParams;
    const from = q.get("from_date") ? Date.parse(q.get("from_date")) : -Infinity;
    const to = q.get("to_date") ? Date.parse(q.get("to_date")) : Infinity;
    const limit = Math.min(Number(q.get("limit") || 50), 100);
    const offset = Number(q.get("offset") || 0);
    return rows
      .filter((r) => !q.get("device_id") || r.device_id === Number(q.get("device_id")))
      .filter((r) => !q.get("species_id") || r.species_id === Number(q.get("species_id")))
      .filter((r) => Date.parse(r.datetime) >= from && Date.parse(r.datetime) <= to)
      .sort((a, b) => Date.parse(b.datetime) - Date.parse(a.datetime) || b.id - a.id)
      .slice(offset, offset + limit);
  };
}

const tiles = () => screen.queryAllByRole("button", { name: /House Sparrow|Pine Siskin/ });
const shownCount = () => document.querySelector(".page-meta-num").textContent;

let rows;
beforeEach(() => {
  const now = Date.now();
  rows = seed(now);
  vi.mocked(apiGet).mockReset().mockImplementation(serve(rows));
  mockData = {
    // Home's window: only the newest 100.
    SIGHTINGS: [],
    SPECIES: [sparrow, siskin],
    SPECIES_COUNTS: [{ ...sparrow, count: 500 }, { ...siskin, count: 1 }],
    DEVICES: [feeder],
    ME: { id: 2, role: "viewer" },
  };
});

describe("History paging", () => {
  it("asks the server with the range, then loads pages back to the oldest visit", async () => {
    render(<Sightings openSighting={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));

    await waitFor(() => expect(tiles()).toHaveLength(HISTORY_PAGE));
    expect(shownCount()).toBe("100+");
    const first = new URL(vi.mocked(apiGet).mock.lastCall[0], "http://x").searchParams;
    expect(first.get("limit")).toBe("100");
    expect(first.has("from_date")).toBe(true);
    expect(first.has("species_id")).toBe(false);

    // Scroll to the end until the server has no more.
    while (screen.queryByRole("button", { name: "Load older visits" })) {
      fireEvent.click(screen.getByRole("button", { name: "Load older visits" }));
      await waitFor(() => expect(screen.queryByRole("button", { name: "Loading…" })).toBeNull());
    }

    expect(tiles()).toHaveLength(501);
    expect(shownCount()).toBe("501");
    // Each later page starts at the oldest loaded row. Five full pages held
    // 500, so the sixth starts at the second oldest sparrow.
    const last = new URL(vi.mocked(apiGet).mock.lastCall[0], "http://x").searchParams;
    expect(vi.mocked(apiGet).mock.calls.filter(([p]) => p.startsWith("/sightings?"))).toHaveLength(7);
    expect(last.get("to_date")).toBe(rows[498].datetime);
    expect(last.get("offset")).toBe("1");
  });

  it("finds a species visit from 25 days ago", async () => {
    render(<Sightings openSighting={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Filter by species" }), {
      target: { value: String(siskin.id) },
    });
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));

    expect(await screen.findByRole("button", { name: /Pine Siskin/ })).toBeInTheDocument();
    expect(tiles()).toHaveLength(1);
    const q = new URL(vi.mocked(apiGet).mock.lastCall[0], "http://x").searchParams;
    expect(q.get("species_id")).toBe(String(siskin.id));
    expect(screen.queryByRole("button", { name: "Load older visits" })).toBeNull();
  });

  it("puts a streamed sighting that matches the filters at the top", async () => {
    render(<Sightings openSighting={() => {}} />);
    await waitFor(() => expect(tiles()).toHaveLength(HISTORY_PAGE));

    act(() => listener({
      type: "sighting",
      sighting: {
        id: 2000, device_id: 1, species_id: siskin.id, classification_tier_used: "gpu",
        confidence_score: 0.9, has_image: true, datetime: new Date().toISOString(),
      },
    }));
    expect(tiles()[0]).toHaveAccessibleName(/Pine Siskin/);
    expect(tiles()).toHaveLength(HISTORY_PAGE + 1);
  });

  it("says select all takes only the loaded visits", async () => {
    mockData.ME = { id: 2, role: "owner" };
    render(<Sightings openSighting={() => {}} />);
    await waitFor(() => expect(tiles()).toHaveLength(HISTORY_PAGE));
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(screen.getByRole("button", { name: `Select all loaded (${HISTORY_PAGE})` })).toBeInTheDocument();
    expect(screen.getByText(/takes the visits loaded so far/)).toBeInTheDocument();
  });
});
