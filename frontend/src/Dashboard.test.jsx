// Home: the latest bird first, today's other visits under it, the quiet-day
// fallbacks, and the two empty states.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { act, render, screen, fireEvent, within } from "@testing-library/react";

let mockData;
let mockFeeder = null;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, feeder: mockFeeder }) }));
const counts = vi.fn();
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchSpeciesCountsBetween: (...args) => counts(...args),
}));

import { Dashboard } from "./Dashboard.jsx";

// Thu 2026-10-29, 7:42 pm local time.
const NOW = new Date(2026, 9, 29, 19, 42);
const FINCH = { id: 1, common: "House Finch", sci: "Haemorhous mexicanus", palette: ["#bf6952"], silhouette: "finch" };
const JAY = { id: 2, common: "Blue Jay", sci: "Cyanocitta cristata", palette: ["#3f6e89"], silhouette: "jay" };
const UNKNOWN = { id: 3, common: "Unknown", sci: "", palette: [], silhouette: "songbird" };
const SQUIRREL = { id: 4, common: "Eastern Gray Squirrel", sci: "Sciurus carolinensis", palette: [],
  silhouette: "songbird", kind: "animal", animalGroup: "squirrel" };
const MAPLE = { id: 1, name: "Backyard Maple", status: "online", lastSeen: "9s ago" };

// hasImage false keeps SightingImage on its plate, with no fetch.
const visit = (id, species, d) => ({ id, species, device: MAPLE, datetime: d, hasImage: false });

function renderHome(sightings, { devices = [MAPLE], feeder = null, ...props } = {}) {
  mockData = { SIGHTINGS: sightings, DEVICES: devices };
  mockFeeder = feeder;
  const openSighting = vi.fn();
  const go = vi.fn();
  const view = render(<Dashboard openSighting={openSighting} go={go} {...props} />);
  return { ...view, openSighting, go };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(NOW);
  // Pending unless a test says otherwise, so the yesterday line stays out.
  counts.mockReset().mockReturnValue(new Promise(() => {}));
});
afterEach(() => vi.useRealTimers());

describe("Home", () => {
  const today = [
    visit(13, FINCH, new Date(2026, 9, 29, 19, 31)),
    visit(12, FINCH, new Date(2026, 9, 29, 19, 29)),
    visit(11, UNKNOWN, new Date(2026, 9, 29, 14, 33)),
    visit(10, JAY, new Date(2026, 9, 28, 17, 24)),
  ];

  it("leads with the latest bird, its feeder and the quiet line", () => {
    renderHome(today);
    const hero = screen.getByRole("region", { name: "Latest visitor" });
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("House Finch");
    expect(hero).toHaveTextContent("11 minutes ago · 7:31 pm");
    expect(hero).toHaveTextContent("Live · Backyard Maple");
    expect(screen.getByText("Quiet for 11 minutes.").parentElement)
      .toHaveTextContent("3 visits today, mostly House Finch.");
  });

  it("says so in one plain sentence when a feeder's Tier 2 stops answering", () => {
    const { unmount } = renderHome(today);
    expect(screen.queryByText(/gaming PC/)).toBeNull();
    unmount();
    const down = { ...MAPLE, id: 2, name: "Porch", tierMix: { tier2Down: true } };
    renderHome(today, { devices: [MAPLE, down] });
    const status = screen.getByText("Quiet for 11 minutes.").parentElement;
    expect(status).toHaveTextContent(
      "The gaming PC has stopped naming birds, so names may be rougher until it is back.");
    expect(status).not.toHaveTextContent(/GPU|Tier|\d+ of/);
  });

  it("opens the hero and earlier visits through openSighting", () => {
    const { openSighting } = renderHome(today);
    fireEvent.click(screen.getByRole("button", { name: "Open the House Finch visit" }));
    expect(openSighting).toHaveBeenLastCalledWith(today[0]);
    fireEvent.click(screen.getByRole("button", { name: "House Finch at 7:29 pm" }));
    expect(openSighting).toHaveBeenLastCalledWith(today[1]);
  });

  it("strips today's other visits only on a busy day, and marks an Unknown one Name?", () => {
    const busy = [visit(14, JAY, new Date(2026, 9, 29, 19, 35)), ...today];
    renderHome(busy);
    expect(screen.getByRole("heading", { name: "Earlier today" })).toBeInTheDocument();
    const strip = screen.getByRole("list");
    const items = within(strip).getAllByRole("button");
    expect(items.map(b => b.textContent)).toEqual(["7:31 pm", "7:29 pm", "Name?"]);
    expect(items[2]).toHaveAccessibleName("Unnamed bird at 2:33 pm");
  });

  it("falls back to recent visits from any day when today is quiet", () => {
    const older = [
      visit(9, JAY, new Date(2026, 9, 27, 8, 5)),
      visit(8, FINCH, new Date(2026, 9, 12, 7, 0)),
    ];
    const { openSighting } = renderHome([...today, ...older]);
    expect(screen.queryByRole("heading", { name: "Earlier today" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent visits" })).toBeInTheDocument();
    const items = within(screen.getByRole("list")).getAllByRole("button");
    expect(items.map(b => b.textContent)).toEqual(["7:29 pm", "Name?", "Yesterday", "Tue", "Oct 12"]);
    expect(items[2]).toHaveAccessibleName("Blue Jay, Yesterday, 5:24 pm");
    fireEvent.click(items[3]);
    expect(openSighting).toHaveBeenLastCalledWith(older[0]);
  });

  it("caps the recent strip at eight, after the hero", () => {
    const many = Array.from({ length: 12 }, (_, i) => visit(100 - i, JAY, new Date(2026, 9, 28, 18, 50 - i)));
    renderHome(many);
    expect(within(screen.getByRole("list")).getAllByRole("button")).toHaveLength(8);
  });

  it("sums up yesterday under the timeline and opens it in History", async () => {
    counts.mockResolvedValue([
      { id: 4, common: "Northern Cardinal", count: 14 },
      { id: 5, common: "American Goldfinch", count: 9 },
      { id: 2, common: "Blue Jay", count: 6 },
      { id: 3, common: "Unknown", count: 2 },
      { id: 6, common: "Mourning Dove", count: 5 },
      { id: 7, common: "House Finch", count: 5 },
    ]);
    const { go } = renderHome([today[3]]);
    const line = await screen.findByRole("button", { name: /^Yesterday/ });
    expect(line).toHaveTextContent(
      "Yesterday41 visits Northern Cardinal 14, American Goldfinch 9, Blue Jay 6 and 2 more species.");
    // Asked of the backend for the whole local day, not counted from the window.
    const [start, end] = counts.mock.calls[0];
    expect(start).toEqual(new Date(2026, 9, 28));
    expect(end).toEqual(new Date(new Date(2026, 9, 29).getTime() - 1));
    fireEvent.click(line);
    expect(go).toHaveBeenCalledWith("history", { day: new Date(2026, 9, 28) });
  });

  it("leaves the yesterday line out when yesterday had no visits", async () => {
    const empty = Promise.resolve([]);
    counts.mockReturnValue(empty);
    renderHome(today);
    await act(() => empty);
    expect(screen.queryByRole("button", { name: /^Yesterday/ })).not.toBeInTheDocument();
  });

  it("marks today's visits on the timeline", () => {
    renderHome(today);
    expect(screen.getByRole("img", { name: "3 visits between 6 am and 9 pm today." })).toBeInTheDocument();
  });

  it("outlines the visit open in the detail view", () => {
    renderHome(today, { selectedId: 12 });
    expect(screen.getByRole("button", { name: "House Finch at 7:29 pm" })).toHaveAttribute("aria-current", "true");
  });

  it("replaces the hero when a new sighting arrives", () => {
    const { rerender, openSighting, go } = renderHome(today);
    const jay = visit(14, JAY, new Date(2026, 9, 29, 19, 41, 40));
    mockData = { SIGHTINGS: [jay, ...today], DEVICES: [MAPLE] };
    rerender(<Dashboard openSighting={openSighting} go={go} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Blue Jay");
    expect(screen.getByText("A visit just now.")).toBeInTheDocument();
  });

  it("shows the last visitor with its day when nothing came today", () => {
    renderHome([today[3]]);
    expect(screen.getByRole("region", { name: "Latest visitor" })).toHaveTextContent("Yesterday, 5:24 pm");
    expect(screen.getByText("No visits yet today.")).toBeInTheDocument();
    expect(screen.queryByText("Earlier today")).not.toBeInTheDocument();
  });

  it("never puts a squirrel in the hero, the strip, or today's count", () => {
    const squirrels = [
      visit(16, SQUIRREL, new Date(2026, 9, 29, 19, 40)),
      visit(15, SQUIRREL, new Date(2026, 9, 29, 19, 35)),
    ];
    renderHome([...squirrels, ...today]);
    const hero = screen.getByRole("region", { name: "Latest visitor" });
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("House Finch");
    expect(screen.getByText("Quiet for 11 minutes.").parentElement)
      .toHaveTextContent("3 visits today, mostly House Finch.");
    expect(screen.queryByText(/Squirrel/)).toBeNull();
  });

  it("points to Feeders with no sightings at all", () => {
    const { go } = renderHome([]);
    expect(screen.getByText("No visits yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check your feeders" }));
    expect(go).toHaveBeenCalledWith("feeders");
  });

  it("asks for a feeder when none is registered", () => {
    const { go } = renderHome([], { devices: [] });
    fireEvent.click(screen.getByRole("button", { name: "Register a feeder" }));
    expect(go).toHaveBeenCalledWith("feeders");
  });
});

describe("Home scoped to one feeder", () => {
  const PORCH = { id: 2, name: "Dad's Porch", status: "online", lastSeen: "1m ago",
    tierMix: { tier2Down: true } };
  const at = (id, species, device, h, m) =>
    ({ id, species, device, datetime: new Date(2026, 9, 29, h, m), hasImage: false });
  const both = [
    at(23, FINCH, MAPLE, 19, 31),
    at(22, JAY, PORCH, 19, 2),
    at(21, FINCH, MAPLE, 18, 40),
    at(20, JAY, PORCH, 9, 15),
  ];

  it("shows only the picked feeder's birds and counts", () => {
    renderHome(both, { devices: [MAPLE, PORCH], feeder: 2 });
    const hero = screen.getByRole("region", { name: "Latest visitor" });
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("Blue Jay");
    expect(hero).toHaveTextContent("Dad's Porch");
    expect(screen.getByText(/visits today/)).toHaveTextContent("2 visits today, all Blue Jay.");
    // The yesterday line asks for the same feeder.
    expect(counts.mock.calls[0][2]).toBe(2);
  });

  it("warns about Tier 2 only for the picked feeder", () => {
    renderHome(both, { devices: [MAPLE, PORCH], feeder: 1 });
    expect(screen.getByText(/visits today/)).toHaveTextContent("2 visits today, all House Finch.");
    expect(screen.queryByText(/stopped naming birds/)).not.toBeInTheDocument();
  });

  it("shows every feeder on All feeders", () => {
    renderHome(both, { devices: [MAPLE, PORCH] });
    expect(screen.getByText(/visits today/)).toHaveTextContent("4 visits today, 2 species.");
    expect(counts.mock.calls[0][2]).toBe(null);
  });
});
