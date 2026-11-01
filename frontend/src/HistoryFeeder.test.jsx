// History opened from a count on one feeder, such as a species page's "All N"
// with the feeder picker set, starts on that feeder.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

let mockData;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: mockData, reload: vi.fn(), subscribe: () => () => {} }),
}));
vi.mock("./SightingImage.jsx", () => ({ SightingImage: () => null }));
vi.mock("./api.js", async (importOriginal) => ({ ...(await importOriginal()), apiGet: vi.fn() }));

import { Sightings } from "./Sightings.jsx";
import { apiGet } from "./api.js";

const MAPLE = { id: 1, name: "Backyard Maple", ownerId: 2 };
const PORCH = { id: 2, name: "Dad's Porch", ownerId: 2 };
const JAY = { id: 5, common: "Blue Jay", palette: [], silhouette: "songbird" };

const visit = (id, device_id) => ({
  id, device_id, species_id: JAY.id, classification_tier_used: "gpu", confidence_score: 0.9,
  has_image: false, datetime: new Date(Date.now() - id * 60000).toISOString(),
});

beforeEach(() => {
  vi.mocked(apiGet).mockReset().mockImplementation(async (path) => {
    const device = new URL(path, "http://x").searchParams.get("device_id");
    return [visit(1, 1), visit(2, 2), visit(3, 2)].filter((r) => !device || r.device_id === Number(device));
  });
  mockData = {
    SIGHTINGS: [], SPECIES: [JAY], SPECIES_COUNTS: [{ ...JAY, count: 3 }],
    DEVICES: [MAPLE, PORCH], ME: { id: 2, role: "viewer" },
  };
});

describe("History's initial feeder", () => {
  it("starts on the feeder it was handed, and asks the server for it", async () => {
    render(<Sightings openSighting={() => {}} initialSpecies={JAY.id} initialDevice={2} />);
    expect(screen.getByRole("combobox", { name: "Filter by feeder" })).toHaveValue("2");
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Blue Jay/ })).toHaveLength(2));
    const q = new URL(vi.mocked(apiGet).mock.lastCall[0], "http://x").searchParams;
    expect(q.get("device_id")).toBe("2");
    expect(q.get("species_id")).toBe(String(JAY.id));
  });

  it("starts on all feeders without one", async () => {
    render(<Sightings openSighting={() => {}} initialSpecies={JAY.id} />);
    expect(screen.getByRole("combobox", { name: "Filter by feeder" })).toHaveValue("all");
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Blue Jay/ })).toHaveLength(3));
  });
});
