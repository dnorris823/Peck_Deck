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

// The context value, for tests that call applyUpdated the way the detail view does.
const useDataHandle = { current: null };

function Probe() {
  const ctx = useData();
  useDataHandle.current = ctx;
  const { data, live } = ctx;
  if (!data) return <div>no-data</div>;
  return (
    <div>
      <div data-testid="ids">{data.SIGHTINGS.map((s) => s.id).join(",")}</div>
      <div data-testid="species">{data.SIGHTINGS.map((s) => s.species_id).join(",")}</div>
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

  it("drops a deleted sighting and refreshes the aggregates, without a full load", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 1 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    fetchRaw.mockClear();
    await handlers.onDeleted(3);

    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent(/^2$/));
    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("1"));
    expect(fetchRaw).not.toHaveBeenCalled();
  });

  it("ignores a delete for a sighting it doesn't hold", async () => {
    // The deleting tab drops the row itself, so its own stream event finds
    // nothing. That must not cost a second aggregate refetch.
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onDeleted(99);

    expect(screen.getByTestId("ids")).toHaveTextContent("3,2");
    expect(fetchAggregates).not.toHaveBeenCalled();
  });

  it("swaps in a corrected sighting and refreshes the aggregates once", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 9 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("species")).toHaveTextContent("1,1"));
    fetchRaw.mockClear();

    const row = { ...BASE.sightings[0], species_id: 1, corrected_at: "2026-10-30T18:00:00+00:00" };
    await useDataHandle.current.applyUpdated(row);
    // The tab that corrected it hears it again on the stream.
    await handlers.onUpdated(row);

    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("9"));
    expect(fetchAggregates).toHaveBeenCalledTimes(1);
    expect(fetchAggregates).toHaveBeenCalledWith();
    expect(fetchRaw).not.toHaveBeenCalled();
  });

  it("swaps in the weather without refetching the aggregates", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onUpdated({ ...BASE.sightings[0], weather_conditions: "4 °C, light snow" });

    await waitFor(() => expect(useDataHandle.current.data.SIGHTINGS[0].weather_conditions)
      .toBe("4 °C, light snow"));
    expect(fetchAggregates).not.toHaveBeenCalled();
  });

  it("applies a correction that arrives after the weather", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 9 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    const weathered = { ...BASE.sightings[0], weather_conditions: "4 °C, light snow" };
    await handlers.onUpdated(weathered);
    await handlers.onUpdated({ ...weathered, species_id: 1, corrected_at: "2026-10-30T18:00:00+00:00" });

    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("9"));
    expect(fetchAggregates).toHaveBeenCalledTimes(1);
  });

  it("loads the species first when the correction names a new one", async () => {
    fetchAggregates.mockResolvedValue({ species: [{ id: 1 }, { id: 5 }] });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("species")).toHaveTextContent("1,1"));

    await handlers.onUpdated({
      ...BASE.sightings[1], species_id: 5, corrected_at: "2026-10-30T18:00:00+00:00",
    });

    await waitFor(() => expect(screen.getByTestId("species")).toHaveTextContent("1,5"));
    expect(fetchAggregates).toHaveBeenCalledWith({ withSpecies: true });
  });

  it("refreshes the counts for a corrected sighting outside the loaded window", async () => {
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 4 } });
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("ids")).toHaveTextContent("3,2"));

    await handlers.onUpdated({
      id: 1, species_id: 1, datetime: "2026-07-01T09:00:00+00:00",
      corrected_at: "2026-10-30T18:00:00+00:00",
    });

    await waitFor(() => expect(screen.getByTestId("today")).toHaveTextContent("4"));
    expect(screen.getByTestId("ids")).toHaveTextContent("3,2");
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
