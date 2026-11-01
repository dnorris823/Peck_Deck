// Home's scoped sightings list in DataContext. With the picker on one feeder,
// Home reads that feeder's newest 100, fetched with device_id, while the full
// list stays for Live, Feeders and History.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";

const handlers = {};
vi.mock("./events.js", () => ({
  openSightingStream: (h) => {
    Object.assign(handlers, h);
    return () => {};
  },
}));

vi.mock("./api.js", () => ({ apiGet: vi.fn() }));

vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),       // fetchScopedSightings and applySighting stay real
  fetchRaw: vi.fn(),
  fetchAggregates: vi.fn(),
  mapAll: (raw) => ({ ...raw, SIGHTINGS: raw.sightings, SCOPED_SIGHTINGS: raw.scopedSightings ?? raw.sightings }),
}));

import { apiGet } from "./api.js";
import { fetchAggregates, fetchRaw } from "./data.js";
import { DataProvider, useData } from "./DataContext.jsx";
import { SCOPE_KEY } from "./feederScope.js";

const row = (id, device_id, hour) =>
  ({ id, species_id: 1, device_id, datetime: `2026-07-30T${String(hour).padStart(2, "0")}:00:00+00:00` });

// Maple (1) is busy, the porch (2) is quiet.
const BASE = {
  sightings: [row(5, 1, 14), row(4, 1, 13), row(3, 1, 12), row(2, 2, 9)],
  species: [{ id: 1 }],
  counts: [], heatmap: [], dashboard: { today_sightings: 4 }, devices: [{ id: 1 }, { id: 2 }],
  scopedSightings: null,
};
const PORCH_WINDOW = [row(2, 2, 9), row(1, 2, 8)];

const handle = { current: null };
function Probe() {
  handle.current = useData();
  const { data } = handle.current;
  if (!data) return <div>no-data</div>;
  return (
    <div>
      <div data-testid="all">{data.SIGHTINGS.map((s) => s.id).join(",")}</div>
      <div data-testid="scoped">{data.SCOPED_SIGHTINGS.map((s) => s.id).join(",")}</div>
    </div>
  );
}

const text = (id) => screen.getByTestId(id).textContent;

async function renderLoaded() {
  render(<DataProvider onAuthError={vi.fn()}><Probe /></DataProvider>);
  await waitFor(() => expect(text("all")).toBe("5,4,3,2"));
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  for (const k of Object.keys(handlers)) delete handlers[k];
  fetchRaw.mockResolvedValue(structuredClone(BASE));
  fetchAggregates.mockResolvedValue({});
  apiGet.mockImplementation((path) => {
    if (path === "/sightings?limit=100&device_id=2") return Promise.resolve(structuredClone(PORCH_WINDOW));
    if (path === "/sightings?limit=100&device_id=1") return Promise.resolve([row(5, 1, 14), row(4, 1, 13), row(3, 1, 12)]);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
});

describe("scoped sightings", () => {
  it("fetches the picked feeder's own newest visits and keeps the full list", async () => {
    await renderLoaded();
    expect(text("scoped")).toBe("5,4,3,2");

    await act(() => handle.current.setFeeder(2));
    expect(apiGet).toHaveBeenCalledWith("/sightings?limit=100&device_id=2");
    // Visit 1 is past the full list's reach, but the porch's own list has it.
    expect(text("scoped")).toBe("2,1");
    expect(text("all")).toBe("5,4,3,2");

    await act(() => handle.current.setFeeder(null));
    expect(text("scoped")).toBe("5,4,3,2");
  });

  it("keeps another feeder's streamed visit out of the scoped list", async () => {
    await renderLoaded();
    await act(() => handle.current.setFeeder(2));

    await act(() => handlers.onSighting(row(6, 1, 15)));
    expect(text("all")).toBe("6,5,4,3,2");
    expect(text("scoped")).toBe("2,1");

    await act(() => handlers.onSighting(row(7, 2, 16)));
    expect(text("scoped")).toBe("7,2,1");
  });

  it("drops a feeder's list that lands after the picker moved on", async () => {
    await renderLoaded();
    let land;
    apiGet.mockImplementationOnce(() => new Promise((resolve) => { land = resolve; }));
    let first;
    act(() => { first = handle.current.setFeeder(2); });
    await act(() => handle.current.setFeeder(1));
    expect(text("scoped")).toBe("5,4,3");

    // The porch's reply arrives late. Maple's list stays.
    await act(async () => { land(structuredClone(PORCH_WINDOW)); await first; });
    expect(text("scoped")).toBe("5,4,3");
  });

  it("deletes from both lists", async () => {
    await renderLoaded();
    await act(() => handle.current.setFeeder(2));
    await act(() => handle.current.applyDeleted(2));
    expect(text("all")).toBe("5,4,3");
    expect(text("scoped")).toBe("1");
  });

  it("loads the saved feeder's list on start", async () => {
    localStorage.setItem(SCOPE_KEY, "2");
    fetchRaw.mockResolvedValue({ ...structuredClone(BASE), scopedSightings: structuredClone(PORCH_WINDOW) });
    render(<DataProvider onAuthError={vi.fn()}><Probe /></DataProvider>);
    await waitFor(() => expect(text("scoped")).toBe("2,1"));
    expect(fetchRaw).toHaveBeenCalledWith({ deviceId: 2 });
  });
});
