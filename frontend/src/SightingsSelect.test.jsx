// History's select mode: tick tiles, then delete them in one request.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

let mockData;
const reload = vi.fn();
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, reload }) }));
// History fetches its own pages. Each test's rows come back as one last page.
let mockRows;
vi.mock("./history.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchHistoryPage: vi.fn(async () => ({ rows: mockRows, done: true })),
}));
vi.mock("./SightingImage.jsx", () => ({ SightingImage: () => null }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  deleteSightings: vi.fn(),
}));

import { Sightings } from "./Sightings.jsx";
import { deleteSightings } from "./data.js";

const mine = { id: 1, name: "Maple", ownerId: 2 };
const shared = { id: 9, name: "Dad's", ownerId: 3 };
const robin = { id: 5, common: "American Robin", palette: [], silhouette: "songbird" };

// A raw row as GET /sightings returns it.
const row = (id, device, minutesAgo) => ({
  id, device_id: device.id, species_id: robin.id, classification_tier_used: "gpu",
  confidence_score: 0.9, has_image: true,
  datetime: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
});

function show(me = { id: 2, role: "viewer" }) {
  mockRows = [row(11, mine, 1), row(12, mine, 2), row(13, shared, 3)];
  mockData = {
    SIGHTINGS: mockRows.map((r) => ({
      id: r.id, species: robin, device: r.device_id === mine.id ? mine : shared,
    })),
    SPECIES: [robin], DEVICES: [mine, shared], ME: me,
  };
  const openSighting = vi.fn();
  render(<Sightings openSighting={openSighting} />);
  return openSighting;
}

const tiles = () => screen.getAllByRole("button", { name: /American Robin/ });

describe("History select mode", () => {
  beforeEach(() => {
    vi.mocked(deleteSightings).mockReset();
    reload.mockReset();
  });

  it("opens a tile until Select is pressed", async () => {
    const openSighting = show();
    await screen.findAllByRole("button", { name: /American Robin/ });
    fireEvent.click(tiles()[0]);
    expect(openSighting).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(tiles()[0]);
    expect(openSighting).toHaveBeenCalledTimes(1);
    expect(tiles()[0]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  it("lets a feeder owner tick only their own feeder's sightings", async () => {
    show();
    await screen.findAllByRole("button", { name: /American Robin/ });
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    // The third tile is on a feeder shared with this viewer.
    expect(tiles()[2]).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select all loaded (2)" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("deletes the ticked sightings after a confirm, then reloads", async () => {
    vi.mocked(deleteSightings).mockResolvedValue({ deleted: 2 });
    show({ id: 1, role: "owner" });
    await screen.findAllByRole("button", { name: /American Robin/ });
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(tiles()[0]);
    fireEvent.click(tiles()[2]);
    fireEvent.click(screen.getByRole("button", { name: "Delete 2…" }));
    expect(deleteSightings).not.toHaveBeenCalled();

    const bar = screen.getByRole("region", { name: "Selected sightings" });
    expect(within(bar).getByText(/Delete 2 sightings and their photos/)).toBeInTheDocument();
    fireEvent.click(within(bar).getByRole("button", { name: "Delete 2" }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(deleteSightings).toHaveBeenCalledWith([11, 13]);
    expect(screen.queryByRole("region", { name: "Selected sightings" })).toBeNull();
    // History drops them from its own pages, not only Home's list.
    expect(tiles()).toHaveLength(1);
  });

  it("shows the server's refusal and keeps the selection", async () => {
    vi.mocked(deleteSightings).mockRejectedValue(new Error("Forbidden"));
    show();
    await screen.findAllByRole("button", { name: /American Robin/ });
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(tiles()[0]);
    fireEvent.click(screen.getByRole("button", { name: "Delete 1…" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete 1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Forbidden");
    expect(reload).not.toHaveBeenCalled();
  });

  it("offers no Select to a user who can delete nothing", () => {
    show({ id: 7, role: "viewer" });
    expect(screen.queryByRole("button", { name: "Select" })).toBeNull();
  });
});
