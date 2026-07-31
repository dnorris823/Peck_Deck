// The dashboard's "Simulate a visit" button (dev tools).
//
// The behaviour worth pinning is the reload. DataContext fetches once on mount
// and never polls, so posting a sighting without refetching leaves the screen
// exactly as it was — the button would appear broken while working perfectly.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("./api.js", () => ({ apiSend: vi.fn(), fetchMeta: vi.fn() }));

const reload = vi.fn();
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ reload }) }));

import { apiSend, fetchMeta } from "./api.js";
import { SimulateVisitButton } from "./Dashboard.jsx";
import { DemoProvider, useDemo } from "./Demo.jsx";

const SIGHTING = {
  id: 501,
  common_name: "Northern Cardinal",
  scientific_name: "Cardinalis cardinalis",
  device_id: 2,
  classification_tier_used: "gpu",
  confidence_score: 0.87,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SimulateVisitButton", () => {
  it("posts a sighting and then refetches the dataset", async () => {
    const user = userEvent.setup();
    apiSend.mockResolvedValue(SIGHTING);

    render(<SimulateVisitButton />);
    await user.click(screen.getByRole("button", { name: /simulate a visit/i }));

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(apiSend).toHaveBeenCalledWith("/dev/sighting", "POST", {});
  });

  it("reports which bird turned up", async () => {
    const user = userEvent.setup();
    apiSend.mockResolvedValue(SIGHTING);

    render(<SimulateVisitButton />);
    await user.click(screen.getByRole("button", { name: /simulate a visit/i }));

    const note = await screen.findByRole("status");
    expect(note).toHaveTextContent(/Northern Cardinal/);
    expect(note).toHaveTextContent(/87%/);
    expect(note).toHaveTextContent(/GPU/);
  });

  it("surfaces the backend's message instead of failing silently", async () => {
    const user = userEvent.setup();
    apiSend.mockRejectedValue(new Error("No species catalogued yet"));

    render(<SimulateVisitButton />);
    await user.click(screen.getByRole("button", { name: /simulate a visit/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/No species catalogued/);
    expect(reload).not.toHaveBeenCalled();
    // Still clickable — a failed attempt must not strand the control.
    expect(screen.getByRole("button")).toBeEnabled();
  });

  it("can't be double-fired while a request is in flight", async () => {
    const user = userEvent.setup();
    let release;
    apiSend.mockReturnValue(new Promise((res) => { release = () => res(SIGHTING); }));

    render(<SimulateVisitButton />);
    const btn = screen.getByRole("button");
    await user.click(btn);

    expect(btn).toBeDisabled();
    release();
    await waitFor(() => expect(btn).toBeEnabled());
    expect(apiSend).toHaveBeenCalledTimes(1);
  });
});

// The gate itself: the button is rendered only where GET /meta says the backend
// would honour it.
function DevToolsProbe() {
  return <span data-testid="flag">{String(useDemo().devTools)}</span>;
}

describe("dev tools flag from /meta", () => {
  it("is off on an instance that doesn't report it", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: false, environment: "development" });
    render(<DemoProvider><DevToolsProbe /></DemoProvider>);

    await waitFor(() => expect(fetchMeta).toHaveBeenCalled());
    expect(screen.getByTestId("flag")).toHaveTextContent("false");
  });

  it("is on when the backend unlocks it", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: false, dev_tools: true });
    render(<DemoProvider><DevToolsProbe /></DemoProvider>);

    await waitFor(() => expect(screen.getByTestId("flag")).toHaveTextContent("true"));
  });
});
