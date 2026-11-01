import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// Mock the data loader so the context's loading/data/error/auth branches are
// driven directly, without any network. `mapAll` passes the raw payload straight
// through, so a test can hand `fetchRaw` the shape it wants to see arrive.
vi.mock("./data.js", () => ({
  fetchRaw: vi.fn(),
  mapAll: (raw) => raw,
  fetchAggregates: vi.fn(),
  fetchScopedSightings: vi.fn(),
  applySighting: vi.fn(),
}));

// These tests are about the load branches. Stub the live stream so they
// don't open a real connection — and, more to the point, so a failed connect
// doesn't leave a reconnect timer armed after the test ends. The streaming
// behaviour has its own file (Stream.test.jsx).
vi.mock("./events.js", () => ({ openSightingStream: () => () => {} }));

import { fetchAggregates, fetchRaw } from "./data.js";
import { SCOPE_KEY } from "./feederScope.js";
import { DataProvider, useData } from "./DataContext.jsx";

// Tiny probe component that renders the context's current state as text.
function Probe() {
  const { data, loading, error } = useData();
  if (loading && !data) return <div>loading</div>;
  if (error) return <div>error: {error}</div>;
  // After an auth error the loader resolves with no data; the real app unmounts
  // this tree, so just render nothing rather than dereferencing null.
  if (!data) return <div>no-data</div>;
  return (
    <div>
      <div>loaded: {data.SPECIES.length} species</div>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

// Shows the scope and the dashboard it loaded, with a button per feeder.
function ScopeProbe() {
  const { data, feeder, setFeeder } = useData();
  if (!data) return <div>loading</div>;
  return (
    <div>
      <div>scope: {String(feeder)}</div>
      <div>today: {data.dashboard.today_sightings}</div>
      <button onClick={() => setFeeder(2)}>Porch</button>
      <button onClick={() => setFeeder(null)}>All</button>
    </div>
  );
}

const TWO_FEEDERS = [{ id: 1 }, { id: 2 }];

describe("DataProvider", () => {
  it("shows loading, then exposes the loaded dataset", async () => {
    fetchRaw.mockResolvedValue({ SPECIES: [{ id: 1 }, { id: 2 }] });
    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );
    expect(screen.getByText("loading")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("loaded: 2 species")).toBeInTheDocument());
  });

  it("surfaces a non-auth error in the error state", async () => {
    fetchRaw.mockRejectedValue(new Error("Can't reach the server."));
    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );
    await waitFor(() =>
      expect(screen.getByText(/error: Can't reach the server\./)).toBeInTheDocument()
    );
  });

  it("calls onAuthError (not the error state) when the load fails auth", async () => {
    const authErr = Object.assign(new Error("expired"), { isAuthError: true });
    fetchRaw.mockRejectedValue(authErr);
    const onAuthError = vi.fn();
    render(
      <DataProvider onAuthError={onAuthError}>
        <Probe />
      </DataProvider>
    );
    await waitFor(() => expect(onAuthError).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/error:/)).not.toBeInTheDocument();
  });

  it("throws if useData is used outside a provider", () => {
    // Silence React's error boundary console noise for this expected throw.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/must be used within a DataProvider/);
    spy.mockRestore();
  });

  it("refetches the aggregates for the picked feeder and keeps the choice", async () => {
    fetchRaw.mockResolvedValue({ devices: TWO_FEEDERS, dashboard: { today_sightings: 6 } });
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 1 } });
    render(<DataProvider onAuthError={vi.fn()}><ScopeProbe /></DataProvider>);
    await waitFor(() => expect(screen.getByText("today: 6")).toBeInTheDocument());
    expect(fetchRaw).toHaveBeenCalledWith({ deviceId: null });

    fireEvent.click(screen.getByText("Porch"));
    await waitFor(() => expect(screen.getByText("today: 1")).toBeInTheDocument());
    expect(screen.getByText("scope: 2")).toBeInTheDocument();
    expect(fetchAggregates).toHaveBeenCalledWith({ deviceId: 2 });
    expect(localStorage.getItem(SCOPE_KEY)).toBe("2");
  });

  it("loads the saved feeder's numbers on start", async () => {
    localStorage.setItem(SCOPE_KEY, "2");
    fetchRaw.mockResolvedValue({ devices: TWO_FEEDERS, dashboard: { today_sightings: 1 } });
    render(<DataProvider onAuthError={vi.fn()}><ScopeProbe /></DataProvider>);
    await waitFor(() => expect(screen.getByText("scope: 2")).toBeInTheDocument());
    expect(fetchRaw).toHaveBeenCalledWith({ deviceId: 2 });
    expect(fetchAggregates).not.toHaveBeenCalled();
  });

  it("falls back to all feeders when the saved one is gone", async () => {
    localStorage.setItem(SCOPE_KEY, "9");
    fetchRaw.mockResolvedValue({ devices: TWO_FEEDERS, dashboard: { today_sightings: 0 } });
    fetchAggregates.mockResolvedValue({ dashboard: { today_sightings: 6 } });
    render(<DataProvider onAuthError={vi.fn()}><ScopeProbe /></DataProvider>);
    await waitFor(() => expect(screen.getByText("today: 6")).toBeInTheDocument());
    expect(screen.getByText("scope: null")).toBeInTheDocument();
    expect(fetchAggregates).toHaveBeenCalledWith({ deviceId: null });
    expect(localStorage.getItem(SCOPE_KEY)).toBe(null);
  });
});
