// The Animals view: the chart, the numbers one tap away, the measure cards,
// and the owner's controls.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

let mockData;
let mockFeeder = null;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, feeder: mockFeeder }) }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchAnimalStats: vi.fn(),
  createMeasure: vi.fn(),
  updateMeasure: vi.fn(),
  deleteMeasure: vi.fn(),
}));

import { createMeasure, deleteMeasure, fetchAnimalStats, updateMeasure } from "./data.js";
import { AnimalsPage } from "./Animals.jsx";

const PORCH = { id: 4, name: "Porch", ownerId: 7 };
const STATS = {
  device_id: 4, tz: "UTC", from_date: "2026-10-01", to_date: "2026-10-03",
  days: [
    { date: "2026-10-01", animals: { squirrel: 3 }, birds: 9 },
    { date: "2026-10-02", animals: { squirrel: 1, raccoon: 2 }, birds: 7 },
    { date: "2026-10-03", animals: {}, birds: 0 },
  ],
  groups: ["squirrel", "raccoon"],
  measures: [{
    id: 11, device_id: 4, name: "Baffle on the pole", note: "Cone baffle",
    started_at: "2026-10-02T12:00:00Z", ended_at: null,
    effect: {
      before_start: "2026-09-18T12:00:00Z", after_start: "2026-10-02T12:00:00Z",
      after_end: "2026-10-16T12:00:00Z", before_hours: 336, after_hours: 336, complete: true,
      groups: { squirrel: { before: 100, after: 28, before_rate: 0.3, after_rate: 0.08, ratio: 0.28, low: 0.17, high: 0.45 } },
      birds: { before: 300, after: 290, before_rate: 0.9, after_rate: 0.86, ratio: 0.97, low: 0.8, high: 1.1 },
    },
  }],
};

function renderPage(me = { id: 7, role: "viewer" }) {
  mockData = { DEVICES: [PORCH], ME: me };
  return render(<AnimalsPage />);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockFeeder = null;
  fetchAnimalStats.mockResolvedValue(STATS);
  createMeasure.mockResolvedValue({});
  updateMeasure.mockResolvedValue({});
  deleteMeasure.mockResolvedValue(null);
});

describe("AnimalsPage", () => {
  it("draws the chart with a marker per measure and a card that says after", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("img", { name: /6 animal visits from 2026-10-01 to 2026-10-03, with 1 measures marked/ })).toBeInTheDocument();
    expect(container.querySelectorAll(".animals-marker")).toHaveLength(1);
    expect(screen.getByText(
      "Squirrel visits down 72% (95% interval 55% to 83%) in the 14 days after Baffle on the pole")).toBeInTheDocument();
    expect(screen.getByText("Birds down 3% over the same days.")).toBeInTheDocument();
    expect(screen.getByText(/what happened after, not proof of why/)).toBeInTheDocument();
    expect(fetchAnimalStats).toHaveBeenCalledWith(4, expect.any(String));
  });

  it("shows the numbers one tap away", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Show the numbers" }));
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("2026-10-02");
    expect(table).not.toHaveTextContent("2026-10-03");  // a day with nothing
  });

  it("hides the owner controls from a viewer of someone else's feeder", async () => {
    renderPage({ id: 9, role: "viewer" });
    await screen.findByText(/Squirrel visits down 72%/);
    expect(screen.queryByRole("button", { name: "End it now" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Log a measure" })).toBeNull();
  });

  it("lets the feeder owner add, end and delete a measure", async () => {
    renderPage();
    await screen.findByText(/Squirrel visits down 72%/);

    fireEvent.change(screen.getByLabelText("What you did"), { target: { value: "Safflower only" } });
    fireEvent.click(screen.getByRole("button", { name: "Add measure" }));
    await waitFor(() => expect(createMeasure).toHaveBeenCalled());
    expect(createMeasure.mock.calls[0][0]).toBe(4);
    expect(createMeasure.mock.calls[0][1].name).toBe("Safflower only");

    fireEvent.click(screen.getByRole("button", { name: "End it now" }));
    await waitFor(() => expect(updateMeasure).toHaveBeenCalledWith(4, 11, { ended_at: expect.any(String) }));

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteMeasure).toHaveBeenCalledWith(4, 11));
    expect(fetchAnimalStats.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("asks for a name before it saves", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Add measure" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Name the measure");
    expect(createMeasure).not.toHaveBeenCalled();
  });

  it("says so when there is nothing yet", async () => {
    fetchAnimalStats.mockResolvedValue({ ...STATS, days: [], groups: [], measures: [] });
    renderPage();
    expect(await screen.findByText("No animal visits in the last 60 days")).toBeInTheDocument();
  });
});

describe("AnimalsPage with two feeders", () => {
  const MAPLE = { id: 1, name: "Backyard Maple", ownerId: 7 };

  it("follows the shell's feeder and drops its own picker", async () => {
    mockData = { DEVICES: [MAPLE, PORCH], ME: { id: 7, role: "viewer" } };
    mockFeeder = 4;
    render(<AnimalsPage />);
    await screen.findByText(/Squirrel visits down 72%/);
    expect(fetchAnimalStats).toHaveBeenCalledWith(4, expect.any(String));
    expect(fetchAnimalStats).not.toHaveBeenCalledWith(1, expect.any(String));
    expect(screen.queryByLabelText("Feeder")).toBeNull();
  });

  it("keeps its own picker on All feeders", async () => {
    mockData = { DEVICES: [MAPLE, PORCH], ME: { id: 7, role: "viewer" } };
    render(<AnimalsPage />);
    await screen.findByText(/Squirrel visits down 72%/);
    expect(fetchAnimalStats).toHaveBeenCalledWith(1, expect.any(String));
    expect(screen.getByLabelText("Feeder")).toBeInTheDocument();
  });
});
