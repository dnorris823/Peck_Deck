import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the data loader so the context's loading/data/error/auth branches are
// driven directly, without any network.
vi.mock("./data.js", () => ({ loadAll: vi.fn() }));

import { loadAll } from "./data.js";
import { DataProvider, useData } from "./DataContext.jsx";

// Tiny probe component that renders the context's current state as text.
function Probe() {
  const { data, loading, error } = useData();
  if (loading) return <div>loading</div>;
  if (error) return <div>error: {error}</div>;
  // After an auth error the loader resolves with no data; the real app unmounts
  // this tree, so just render nothing rather than dereferencing null.
  if (!data) return <div>no-data</div>;
  return <div>loaded: {data.SPECIES.length} species</div>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("DataProvider", () => {
  it("shows loading, then exposes the loaded dataset", async () => {
    loadAll.mockResolvedValue({ SPECIES: [{ id: 1 }, { id: 2 }] });
    render(
      <DataProvider onAuthError={vi.fn()}>
        <Probe />
      </DataProvider>
    );
    expect(screen.getByText("loading")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("loaded: 2 species")).toBeInTheDocument());
  });

  it("surfaces a non-auth error in the error state", async () => {
    loadAll.mockRejectedValue(new Error("Can't reach the server."));
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
    loadAll.mockRejectedValue(authErr);
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
});
