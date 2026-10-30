// The delete button on the sighting detail view: who sees it, and the confirm
// step in front of DELETE /sightings/{id}.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const applyDeleted = vi.fn();
let me;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: { SPECIES_COUNTS: [], ME: me }, applyDeleted }),
}));

vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  deleteSighting: vi.fn(),
}));

import { deleteSighting } from "./data.js";
import { SightingDetail, canDeleteSighting } from "./Sightings.jsx";

const S = {
  id: 12,
  species: {
    id: 1, common: "Gray Squirrel", sci: "Sciurus carolinensis",
    palette: ["#777", "#333", "#ccc"], silhouette: "songbird",
  },
  device: { id: 4, name: "Window", ownerId: 7 },
  datetime: new Date("2026-10-29T12:00:00Z"),
  confidence: 0.9,
  tier: "gpu",
  hasImage: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  me = { id: 7, role: "viewer" };
});

describe("canDeleteSighting", () => {
  it("lets the device owner delete, whatever their role", () => {
    expect(canDeleteSighting(S, { id: 7, role: "viewer" })).toBe(true);
  });

  it("lets an owner-role user delete on any device", () => {
    expect(canDeleteSighting(S, { id: 8, role: "owner" })).toBe(true);
  });

  it("hides it from a viewer who doesn't own the device", () => {
    expect(canDeleteSighting(S, { id: 8, role: "viewer" })).toBe(false);
  });
});

describe("delete button", () => {
  it("asks for confirmation before deleting", async () => {
    deleteSighting.mockResolvedValue(null);
    const onClose = vi.fn();
    render(<SightingDetail s={S} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteSighting).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete this sighting" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(deleteSighting).toHaveBeenCalledWith(12);
    expect(applyDeleted).toHaveBeenCalledWith(12);
  });

  it("keeps the dialog open and says why when the delete fails", async () => {
    deleteSighting.mockRejectedValue(new Error("Request to /sightings/12 failed (403)."));
    const onClose = vi.fn();
    render(<SightingDetail s={S} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete this sighting" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("403");
    expect(onClose).not.toHaveBeenCalled();
    expect(applyDeleted).not.toHaveBeenCalled();
  });

  it("is absent for a viewer who doesn't own the device", () => {
    me = { id: 8, role: "viewer" };
    render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});
