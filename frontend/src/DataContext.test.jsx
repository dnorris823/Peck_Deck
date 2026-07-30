import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the data loader so the context's loading/data/error/auth branches are
// driven directly, without any network. `mapAll` passes the raw payload straight
// through, so a test can hand `fetchRaw` the shape it wants to see arrive.
vi.mock("./data.js", () => ({
  fetchRaw: vi.fn(),
  mapAll: (raw) => raw,
  fetchAggregates: vi.fn(),
  applySighting: vi.fn(),
}));

// These tests are about the load/snapshot branches. Stub the live stream so they
// don't open a real connection — and, more to the point, so a failed connect
// doesn't leave a reconnect timer armed after the test ends. The streaming
// behaviour has its own file (Stream.test.jsx).
vi.mock("./events.js", () => ({ openSightingStream: () => () => {} }));

import { fetchRaw } from "./data.js";
import { DataProvider, useData } from "./DataContext.jsx";
import { clearSnapshot, saveSnapshot } from "./offline.js";

// Tiny probe component that renders the context's current state as text.
function Probe() {
  const { data, loading, error, stale } = useData();
  if (loading && !data) return <div>loading</div>;
  if (error) return <div>error: {error}</div>;
  // After an auth error the loader resolves with no data; the real app unmounts
  // this tree, so just render nothing rather than dereferencing null.
  if (!data) return <div>no-data</div>;
  return (
    <div>
      <div>loaded: {data.SPECIES.length} species</div>
      {stale && <div>stale</div>}
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  clearSnapshot();
});

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
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
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

  // ── Offline-tolerant reads (Phase 7) ──────────────────────────────────────
  it("paints the snapshot immediately, before the network answers", async () => {
    saveSnapshot({ SPECIES: [{ id: 1 }] });
    let resolve;
    fetchRaw.mockReturnValue(new Promise((r) => { resolve = r; }));

    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );

    // The point of the snapshot: content on the very first render, not a spinner.
    expect(screen.getByText("loaded: 1 species")).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument();

    resolve({ SPECIES: [{ id: 1 }, { id: 2 }, { id: 3 }] });
    await waitFor(() => expect(screen.getByText("loaded: 3 species")).toBeInTheDocument());
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
  });

  it("keeps showing cached data (flagged stale) when the refresh fails", async () => {
    saveSnapshot({ SPECIES: [{ id: 1 }, { id: 2 }] });
    fetchRaw.mockRejectedValue(new Error("Can't reach the server."));

    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );

    await waitFor(() => expect(screen.getByText("stale")).toBeInTheDocument());
    // Cached content beats an error page when there is something to show.
    expect(screen.getByText("loaded: 2 species")).toBeInTheDocument();
    expect(screen.queryByText(/error:/)).not.toBeInTheDocument();
  });

  it("saves a snapshot after a successful load", async () => {
    fetchRaw.mockResolvedValue({ SPECIES: [{ id: 7 }] });
    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );
    await waitFor(() => expect(screen.getByText("loaded: 1 species")).toBeInTheDocument());

    expect(JSON.parse(localStorage.getItem("peckdeck_snapshot")).raw)
      .toEqual({ SPECIES: [{ id: 7 }] });
  });

  it("discards the snapshot when the session has expired", async () => {
    // It holds the previous user's records — it must not survive their session.
    saveSnapshot({ SPECIES: [{ id: 1 }] });
    fetchRaw.mockRejectedValue(Object.assign(new Error("expired"), { isAuthError: true }));

    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );

    await waitFor(() => expect(localStorage.getItem("peckdeck_snapshot")).toBeNull());
  });
});
