// The Live screen with live.js mocked: the offline panel, the feeder dropdown
// and its memory, the readout, and the corner pill for a new visit.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";

const store = vi.hoisted(() => ({ data: null }));
const player = vi.hoisted(() => ({ calls: [], stop: null }));

vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: store.data, reload: () => {}, loading: false }),
}));
vi.mock("./live.js", () => ({
  openLiveStream: (opts) => {
    player.calls.push(opts);
    return player.stop;
  },
}));

import { LivePage, FEEDER_KEY, PILL_MS, pickFeeder, pillText } from "./Live.jsx";

const garden = {
  id: 1, name: "Garden", status: "online", liveAvailable: true, todaySightings: 4,
  lastSeenAt: new Date(), lastSeen: "just now",
};
const porch = {
  id: 2, name: "Porch", status: "offline", liveAvailable: false, todaySightings: 0,
  lastSeenAt: new Date(2026, 9, 30, 7, 31), lastSeen: "6h ago",
};
const cardinal = { id: 10, common: "Northern Cardinal" };
const unknown = { id: 11, common: "Unknown" };

function sighting(id, device, species = cardinal, extra = {}) {
  return { id, device, species, confidence: 0.92, datetime: new Date(), delayed: false, ...extra };
}

beforeEach(() => {
  player.calls = [];
  player.stop = vi.fn();
  store.data = { DEVICES: [garden, porch], SIGHTINGS: [sighting(1, garden)] };
});

afterEach(() => vi.useRealTimers());

describe("pickFeeder", () => {
  it("prefers the remembered feeder, then one that can stream", () => {
    expect(pickFeeder([porch, garden], "2")).toBe(porch);
    expect(pickFeeder([porch, garden], null)).toBe(garden);
    expect(pickFeeder([porch, garden], "99")).toBe(garden);
    expect(pickFeeder([], null)).toBe(null);
  });
});

describe("pillText", () => {
  it("names the species with its confidence, or says a bird is here", () => {
    expect(pillText(sighting(1, garden))).toBe("Northern Cardinal 92%");
    expect(pillText(sighting(1, garden, unknown))).toBe("Bird here");
  });
});

describe("LivePage", () => {
  it("plays a feeder that can stream and shows the status strip", () => {
    render(<LivePage go={() => {}} />);
    expect(player.calls).toHaveLength(1);
    expect(player.calls[0].deviceId).toBe(1);
    expect(screen.getByText("4 visits today")).toBeInTheDocument();

    act(() => player.calls[0].onStatus({ phase: "live", fps: 30, delayMs: 140, unreachable: false }));
    expect(screen.getByText("Live · 30 fps · 140 ms")).toBeInTheDocument();
    expect(screen.getByText("30 fps")).toBeInTheDocument();
  });

  it("shows the offline panel and never starts a feeder that cannot stream", () => {
    localStorage.setItem(FEEDER_KEY, "2");
    render(<LivePage go={() => {}} />);
    expect(player.calls).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Porch isn't streaming" })).toBeInTheDocument();
    expect(screen.getByText(/Last heartbeat 7:31 am/)).toBeInTheDocument();
    expect(screen.getByText("mediamtx.service")).toBeInTheDocument();
  });

  it("shows the offline panel when the feeder answers 503", () => {
    render(<LivePage go={() => {}} />);
    act(() => player.calls[0].onStatus({ phase: "offline", fps: null, delayMs: null, unreachable: false }));
    expect(screen.getByRole("heading", { name: "Garden isn't streaming" })).toBeInTheDocument();
  });

  it("says live video needs the home network after repeated failures", () => {
    render(<LivePage go={() => {}} />);
    act(() => player.calls[0].onStatus({ phase: "reconnecting", fps: null, delayMs: null, unreachable: true }));
    expect(screen.getByText(/needs the home network or Tailscale/)).toBeInTheDocument();
  });

  it("remembers the feeder chosen in the dropdown", () => {
    render(<LivePage go={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Feeder" }), { target: { value: "2" } });
    expect(localStorage.getItem(FEEDER_KEY)).toBe("2");
    expect(player.stop).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Porch isn't streaming" })).toBeInTheDocument();
  });

  it("hides the dropdown with one feeder", () => {
    store.data = { DEVICES: [garden], SIGHTINGS: [] };
    render(<LivePage go={() => {}} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows a new visit from this feeder in the corner for 60 seconds", () => {
    vi.useFakeTimers();
    const { rerender } = render(<LivePage go={() => {}} />);
    // The visit that was already there when the tab opened is not news.
    expect(screen.queryByText(/Northern Cardinal/)).not.toBeInTheDocument();

    // A new visit at the other feeder is not shown.
    store.data = { ...store.data, SIGHTINGS: [sighting(2, porch), ...store.data.SIGHTINGS] };
    rerender(<LivePage go={() => {}} />);
    expect(screen.queryByText(/Northern Cardinal/)).not.toBeInTheDocument();

    store.data = { ...store.data, SIGHTINGS: [sighting(3, garden, unknown), ...store.data.SIGHTINGS] };
    rerender(<LivePage go={() => {}} />);
    expect(screen.getByText("Bird here")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(PILL_MS));
    expect(screen.queryByText("Bird here")).not.toBeInTheDocument();
  });

  it("ignores a late visit from the offline queue", () => {
    const { rerender } = render(<LivePage go={() => {}} />);
    store.data = { ...store.data, SIGHTINGS: [sighting(4, garden, cardinal, { delayed: true }), ...store.data.SIGHTINGS] };
    rerender(<LivePage go={() => {}} />);
    expect(screen.queryByText(/Northern Cardinal/)).not.toBeInTheDocument();
  });
});
