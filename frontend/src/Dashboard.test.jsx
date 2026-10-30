// Home: the latest bird first, today's other visits under it, and the two
// empty states.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

let mockData;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData }) }));

import { Dashboard } from "./Dashboard.jsx";

// Thu 2026-10-29, 7:42 pm local time.
const NOW = new Date(2026, 9, 29, 19, 42);
const FINCH = { id: 1, common: "House Finch", sci: "Haemorhous mexicanus", palette: ["#bf6952"], silhouette: "finch" };
const JAY = { id: 2, common: "Blue Jay", sci: "Cyanocitta cristata", palette: ["#3f6e89"], silhouette: "jay" };
const UNKNOWN = { id: 3, common: "Unknown", sci: "", palette: [], silhouette: "songbird" };
const MAPLE = { id: 1, name: "Backyard Maple", status: "online", lastSeen: "9s ago" };

// hasImage false keeps SightingImage on its plate, with no fetch.
const visit = (id, species, d) => ({ id, species, device: MAPLE, datetime: d, hasImage: false });

function renderHome(sightings, { devices = [MAPLE], ...props } = {}) {
  mockData = { SIGHTINGS: sightings, DEVICES: devices };
  const openSighting = vi.fn();
  const go = vi.fn();
  const view = render(<Dashboard openSighting={openSighting} go={go} {...props} />);
  return { ...view, openSighting, go };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(NOW);
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

  it("strips today's other visits only, and marks an Unknown one Name?", () => {
    renderHome(today);
    const strip = screen.getByRole("list");
    const items = within(strip).getAllByRole("button");
    expect(items.map(b => b.textContent)).toEqual(["7:29 pm", "Name?"]);
    expect(items[1]).toHaveAccessibleName("Unnamed bird at 2:33 pm");
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
