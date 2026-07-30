// How DataContext applies a streamed sighting.
//
// The point of the stream is that a new visit costs no refetch of the feed —
// the event carries the row. What it *does* cost is a refetch of the aggregates
// derived from it, because recomputing those in the browser would be a second
// implementation of the backend's aggregation, drifting against the first.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

const handlers = {};
vi.mock("./events.js", () => ({
  openSightingStream: (h) => {
    Object.assign(handlers, h);
    return () => { handlers.stopped = true; };
  },
}));

vi.mock("./api.js", () => ({ apiGet: vi.fn() }));

import { fetchRaw, fetchAggregates } from "./data.js";
import { applySighting } from "./data.js";
import { DataProvider, useData } from "./DataContext.jsx";
import { clearSnapshot } from "./offline.js";

vi.mock("./data.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,                       // applySighting stays real — it's under test
    fetchRaw: vi.fn(),
    fetchAggregates: vi.fn(),
    mapAll: (raw) => ({ ...raw, SIGHTINGS: raw.sightings }),
  };
});

const BASE = {
  sightings: [
    { id: 3, species_id: 1, datetime: "2026-07-30T12:00:00+00:00" },
    { id: 2, species_id: 1, datetime: "2026-07-30T09:00:00+00:00" },
  ],
  species: [{ id: 1 }],
  counts: [], heatmap: [], dashboard: { today_sightings: 2 }, devices: [],
};

function Probe() {
  const { data, live } = useData();
  if (!data) return <div>no-data</div>;
  return (
    <div>
      <div data-testid="ids">{data.SIGHTINGS.map((s) => s.id).join(",")}</div>
      <div data-testid="today">{data.dashboard.today_sightings}</div>
      <div data-testid="live">{String(live)}</div>
    </div>
  );
}

function renderProvider(onAuthError = vi.fn()) {
  return render(<DataProvider onAuthError={onAuthError}><Probe /></DataProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  clearSnapshot();
  for (const k of Object.keys(handlers)) delete handlers[k];
  fetchRaw.mockResolvedValue(structuredClone(BASE));
});

describe("streamed sightings", () => {
  it("shows a new visit without refetching the feed", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 3 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    fetchRaw.mockClear();
    await handlers.onSighting({ id: 4, species_id: 1, datetime: "2026-07-30T15:00:00+00:00" });

    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("4,3,2"));
    // The whole point: no second full load.
    expect(fetchRaw).not.toHaveBeenCalled();
  });

  it("refreshes the aggregates the new visit invalidated", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 3 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("2"));

    await handlers.onSighting({ id: 4, species_id: 1, datetime: "2026-07-30T15:00:00+00:00" });

    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("3"));
  });

  it("also pulls species when the bird is one the client has never seen", async () => {
    // mapAll drops any sighting it can't join to a species, so a first-ever
    // visit would arrive and silently vanish.
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 3 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onSighting({ id: 4, species_id: 99, datetime: "2026-07-30T15:00:00+00:00" });

    await waitFor(() => expect(fetchAggregates).toHaveBeenCalledWith({ withSpecies: true }));
  });

  it("doesn't pull species for a bird already in the catalogue", async () => {
    fetchAggregates.mockResolvedValue({});
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onSighting({ id: 4, species_id: 1, datetime: "2026-07-30T15:00:00+00:00" });

    await waitFor(() => expect(fetchAggregates).toHaveBeenCalledWith({ withSpecies: false }));
  });

  it("keeps the feed on screen when the aggregate refetch fails", async () => {
    fetchAggregates.mockRejectedValue(new Error("network"));
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onSighting({ id: 4, species_id: 1, datetime: "2026-07-30T15:00:00+00:00" });

    // The sighting is correct; only the derived numbers lag a beat.
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("4,3,2"));
    expect(screen.getByTestId("today")).toHaveTextContent("2");
  });

  it("ignores a replayed duplicate", async () => {
    fetchAggregates.mockResolvedValue({});
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    // Reconnect replay overlaps by design: the stream subscribes before it
    // queries, so an event can arrive twice.
    await handlers.onSighting({ id: 3, species_id: 1, datetime: "2026-07-30T12:00:00+00:00" });

    expect(screen.getByTestId("ids")).toHaveTextContent("3,2");
    expect(fetchAggregates).not.toHaveBeenCalled();
  });

  it("does a full reload on resync", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));
    fetchRaw.mockClear();

    await handlers.onResync();

    await waitFor(() => expect(fetchRaw).toHaveBeenCalledTimes(1));
  });

  it("exposes the connection status", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("false"));

    handlers.onStatus(true);
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("true"));
  });

  it("closes the stream when the provider unmounts", async () => {
    const { unmount } = renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toBeInTheDocument());

    unmount();

    expect(handlers.stopped).toBe(true);
  });
});

// applySighting is the ordering rule, and the reason it isn't a plain unshift.
describe("applySighting", () => {
  const rows = [
    { id: 3, datetime: "2026-07-30T12:00:00+00:00" },
    { id: 2, datetime: "2026-07-30T09:00:00+00:00" },
  ];

  it("puts a newer visit first", () => {
    const out = applySighting(rows, { id: 4, datetime: "2026-07-30T15:00:00+00:00" });
    expect(out.map((s) => s.id)).toEqual([4, 3, 2]);
  });

  it("files a backdated capture by its timestamp, not its id", () => {
    // The Pi's offline queue uploads this morning's captures when it
    // reconnects, so the highest id can be the oldest visit. Prepending would
    // put it above visits that actually happened later.
    const out = applySighting(rows, { id: 9, datetime: "2026-07-30T10:30:00+00:00" });
    expect(out.map((s) => s.id)).toEqual([3, 9, 2]);
  });

  it("appends one older than everything held", () => {
    const out = applySighting(rows, { id: 9, datetime: "2026-07-29T08:00:00+00:00" });
    expect(out.map((s) => s.id)).toEqual([3, 2, 9]);
  });

  it("returns the same array for a duplicate, so callers can skip the work", () => {
    expect(applySighting(rows, { id: 3, datetime: "2026-07-30T12:00:00+00:00" })).toBe(rows);
  });

  it("holds the list to the same window a full load would produce", () => {
    const many = Array.from({ length: 100 }, (_, i) => ({
      id: 1000 - i,
      datetime: new Date(Date.UTC(2026, 6, 30, 12) - i * 60000).toISOString(),
    }));
    const out = applySighting(many, { id: 2000, datetime: "2026-07-30T13:00:00+00:00" });
    expect(out).toHaveLength(100);
    expect(out[0].id).toBe(2000);
  });
});
