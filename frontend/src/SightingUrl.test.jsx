// The per-sighting URL. A push notification links to /?sighting=<id>, so the
// app has to open that sighting on boot, whether or not it is in the loaded
// window, and the URL has to follow the view as it opens, moves and closes.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

const SPECIES = { id: 1, common: "House Finch", sci: "Haemorhous mexicanus", palette: ["#bf6952"] };
const DEVICE = { id: 4, name: "Backyard Maple", ownerId: 7 };
const sighting = (id, hour) => ({
  id, species: SPECIES, device: DEVICE, datetime: new Date(2026, 9, 28, hour),
  confidence: 0.71, tier: "gpu", hasImage: false, delayed: false, tierTrace: null,
});
const DATA = {
  SIGHTINGS: [sighting(12, 19), sighting(11, 16)],
  SPECIES: [SPECIES],
  DEVICES: [DEVICE],
  SPECIES_COUNTS: [],
  ME: { id: 7, name: "Dom", role: "owner" },
};

vi.mock("./DataContext.jsx", () => ({
  DataProvider: ({ children }) => children,
  useData: () => ({ data: DATA, loading: false, error: null, live: true, reload: () => {}, applyDeleted: () => {} }),
}));
vi.mock("./api.js", async (importOriginal) => ({ ...(await importOriginal()), getToken: () => "token" }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchSighting: vi.fn(),
  fetchSpeciesHours: () => Promise.resolve({ peak_hours: [] }),
}));
vi.mock("./history.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchDayVisits: () => Promise.resolve([]),
}));
// A visit older than Home's list, as History hands one over.
const OLD = { ...sighting(3, 9), datetime: new Date(2026, 6, 1, 9) };
// A stub Home that opens a sighting the way every screen does, and reports the
// visit it was told to outline.
vi.mock("./Dashboard.jsx", () => ({
  Dashboard: ({ openSighting, selectedId }) => (
    <>
      <button onClick={() => openSighting(DATA.SIGHTINGS[1])}>open 11</button>
      <button onClick={() => openSighting(OLD)}>open old</button>
      <output aria-label="Outlined visit">{selectedId ?? "none"}</output>
    </>
  ),
}));

import App, { sightingFromUrl, urlWithSighting } from "./App.jsx";
import { fetchSighting } from "./data.js";

const dialog = () => screen.queryByRole("dialog");

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("sightingFromUrl", () => {
  it("reads a positive integer id", () => {
    expect(sightingFromUrl("?sighting=12")).toBe(12);
    expect(sightingFromUrl("?screen=history&sighting=3")).toBe(3);
  });

  it("ignores anything else", () => {
    expect(sightingFromUrl("")).toBeNull();
    expect(sightingFromUrl("?sighting=abc")).toBeNull();
    expect(sightingFromUrl("?sighting=-1")).toBeNull();
    expect(sightingFromUrl("?sighting=1.5")).toBeNull();
  });
});

describe("urlWithSighting", () => {
  const loc = { pathname: "/", search: "?screen=history", hash: "" };

  it("keeps the other parameters", () => {
    expect(urlWithSighting(12, loc)).toBe("/?screen=history&sighting=12");
  });

  it("drops the parameter for null", () => {
    expect(urlWithSighting(null, { ...loc, search: "?sighting=12" })).toBe("/");
  });
});

describe("opening from the URL", () => {
  it("opens a loaded sighting on boot, as a push notification click does", () => {
    window.history.replaceState(null, "", "/?sighting=12");
    render(<App />);
    expect(dialog()).toHaveAccessibleName("House Finch sighting");
    expect(fetchSighting).not.toHaveBeenCalled();
  });

  it("fetches a sighting outside the loaded window", async () => {
    const old = { ...sighting(3, 9), datetime: new Date(2026, 6, 1, 9) };
    fetchSighting.mockResolvedValue(old);
    window.history.replaceState(null, "", "/?sighting=3");
    render(<App />);
    await waitFor(() => expect(dialog()).not.toBeNull());
    expect(fetchSighting).toHaveBeenCalledWith(3, DATA);
  });

  it("closes and clears the URL when the sighting is gone", async () => {
    fetchSighting.mockRejectedValue(new Error("Request to /sightings/404 failed (404)."));
    window.history.replaceState(null, "", "/?sighting=404");
    render(<App />);
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(dialog()).toBeNull();
  });

  it("rewrites the URL on close, since there is no entry of ours to go back to", () => {
    window.history.replaceState(null, "", "/?sighting=12");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Close sighting" }));
    expect(dialog()).toBeNull();
    expect(window.location.search).toBe("");
  });
});

describe("opening from a screen", () => {
  it("pushes the URL, replaces it along the strip, and closes on Back", async () => {
    render(<App />);
    const before = window.history.length;

    fireEvent.click(screen.getByRole("button", { name: "open 11" }));
    expect(window.location.search).toBe("?sighting=11");
    expect(window.history.length).toBe(before + 1);

    fireEvent.click(screen.getByRole("button", { name: "Newer visit" }));
    expect(window.location.search).toBe("?sighting=12");
    expect(window.history.length).toBe(before + 1);

    await act(async () => {
      window.history.back();
      await new Promise(r => window.addEventListener("popstate", r, { once: true }));
    });
    expect(dialog()).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("shows a handed-over visit older than Home's list without fetching it again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "open old" }));
    expect(window.location.search).toBe("?sighting=3");
    expect(dialog()).toHaveAccessibleName("House Finch sighting");
    expect(fetchSighting).not.toHaveBeenCalled();
  });

  it("tells Home which visit is open, as it moves and when it closes", () => {
    render(<App />);
    const outlined = () => screen.getByRole("status", { name: "Outlined visit" });
    expect(outlined()).toHaveTextContent("none");

    fireEvent.click(screen.getByRole("button", { name: "open 11" }));
    expect(outlined()).toHaveTextContent("11");

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(outlined()).toHaveTextContent("12");

    fireEvent.click(screen.getByRole("button", { name: "Close sighting" }));
    expect(outlined()).toHaveTextContent("none");
  });
});
