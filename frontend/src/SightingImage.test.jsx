import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("./api.js", () => ({ apiObjectUrl: vi.fn() }));

import { apiObjectUrl } from "./api.js";
import { SightingImage } from "./SightingImage.jsx";

const SPECIES = {
  id: 1, common: "Blue Jay", sci: "Cyanocitta cristata",
  palette: ["#7a8a8c", "#2a3032", "#d4cdb8"], silhouette: "jay",
};
const sighting = (hasImage) => ({ id: 42, hasImage, species: SPECIES });

// Captures the observers the component creates so a test can decide when the
// tile "scrolls into view".
let observers;

beforeEach(() => {
  vi.clearAllMocks();
  observers = [];
  class FakeIntersectionObserver {
    constructor(callback) {
      this.callback = callback;
      observers.push(this);
    }
    observe() {}
    disconnect() {}
    enter() { this.callback([{ isIntersecting: true }]); }
  }
  globalThis.IntersectionObserver = FakeIntersectionObserver;
  window.IntersectionObserver = FakeIntersectionObserver;
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  delete globalThis.IntersectionObserver;
  delete window.IntersectionObserver;
});

describe("SightingImage", () => {
  it("shows the species plate and fetches nothing before the tile is in view", () => {
    apiObjectUrl.mockResolvedValue("blob:photo");
    render(<SightingImage sighting={sighting(true)} />);

    // This is the whole point on a phone: 100 tiles must not mean 100 fetches.
    expect(apiObjectUrl).not.toHaveBeenCalled();
    expect(document.querySelector(".bird-plate")).toBeTruthy();
    expect(screen.queryByRole("img", { name: /Blue Jay/ })).not.toBeInTheDocument();
  });

  it("loads the capture photo once the tile scrolls into view", async () => {
    apiObjectUrl.mockResolvedValue("blob:photo");
    render(<SightingImage sighting={sighting(true)} />);

    observers[0].enter();

    await waitFor(() =>
      expect(screen.getByRole("img", { name: "Photo of Blue Jay" })).toBeInTheDocument()
    );
    expect(apiObjectUrl).toHaveBeenCalledWith("/sightings/42/image");
    expect(screen.getByRole("img", { name: "Photo of Blue Jay" }))
      .toHaveAttribute("src", "blob:photo");
  });

  it("never observes or fetches for a sighting with no stored image", () => {
    render(<SightingImage sighting={sighting(false)} />);
    expect(observers).toHaveLength(0);
    expect(apiObjectUrl).not.toHaveBeenCalled();
    expect(document.querySelector(".bird-plate")).toBeTruthy();
  });

  it("keeps the plate when the photo can't be fetched", async () => {
    apiObjectUrl.mockRejectedValue(new Error("404"));
    render(<SightingImage sighting={sighting(true)} />);

    observers[0].enter();

    await waitFor(() => expect(apiObjectUrl).toHaveBeenCalled());
    // A missing photo is not worth an error state — the plate is a real fallback.
    expect(document.querySelector(".capture-img")).toBeNull();
    expect(document.querySelector(".bird-plate")).toBeTruthy();
  });

  it("revokes the object URL on unmount", async () => {
    apiObjectUrl.mockResolvedValue("blob:photo");
    const { unmount } = render(<SightingImage sighting={sighting(true)} />);

    observers[0].enter();
    await waitFor(() => expect(document.querySelector(".capture-img")).toBeTruthy());
    unmount();

    // Without this a long scroll retains every JPEG it passed.
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo");
  });

  it("loads immediately when the browser has no IntersectionObserver", async () => {
    delete globalThis.IntersectionObserver;
    delete window.IntersectionObserver;
    apiObjectUrl.mockResolvedValue("blob:photo");

    render(<SightingImage sighting={sighting(true)} />);

    // Degraded, but never blank.
    await waitFor(() => expect(apiObjectUrl).toHaveBeenCalledWith("/sightings/42/image"));
  });
});
