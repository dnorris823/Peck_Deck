// The Compare view: a card per feeder, the species only it saw, and the first
// of year table. The server leaves out feeders the user cannot see, so the page
// draws exactly the feeders in the reply.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

let mockData;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData }) }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchCompare: vi.fn(),
}));

import { fetchCompare } from "./data.js";
import { ComparePage } from "./Compare.jsx";

const HOME = { id: 1, name: "Home" };
const DADS = { id: 2, name: "Dad's" };
const COMPARE = {
  year: 2026,
  feeders: [
    { device_id: 1, name: "Home", visits_week: 1234, species_year: 2, busiest_hour: 8 },
    { device_id: 2, name: "Dad's", visits_week: 0, species_year: 1, busiest_hour: null },
  ],
  species: [
    { id: 10, common_name: "Blue Jay", genus: "C", species_name: "c", palette: ["#3f6e89"],
      firsts: [{ device_id: 1, first_seen: "2026-03-02T15:00:00Z" }] },
    { id: 12, common_name: "Northern Cardinal", genus: "C", species_name: "c", palette: [],
      firsts: [
        { device_id: 2, first_seen: "2026-01-04T15:00:00Z" },
        { device_id: 1, first_seen: "2026-01-09T15:00:00Z" },
      ] },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  fetchCompare.mockResolvedValue(COMPARE);
  mockData = { DEVICES: [HOME, DADS], ME: { id: 7, role: "viewer" } };
});

describe("ComparePage", () => {
  it("draws a card per feeder with its week, year and busiest hour", async () => {
    render(<ComparePage go={() => {}} />);
    const home = (await screen.findByRole("heading", { name: "Home" })).closest("article");
    expect(within(home).getByText("1,234")).toBeInTheDocument();
    expect(within(home).getByText("Species in 2026")).toBeInTheDocument();
    expect(within(home).getByText("8 am")).toBeInTheDocument();
    const dads = screen.getByRole("heading", { name: "Dad's" }).closest("article");
    expect(within(dads).getByText("None")).toBeInTheDocument();
  });

  it("lists the species only one feeder saw on that feeder's card", async () => {
    render(<ComparePage go={() => {}} />);
    const home = (await screen.findByRole("heading", { name: "Home" })).closest("article");
    expect(within(home).getByRole("listitem")).toHaveTextContent("Blue Jay");
    const dads = screen.getByRole("heading", { name: "Dad's" }).closest("article");
    expect(within(dads).queryByRole("listitem")).toBeNull();
    expect(within(dads).getByText(/seen at another feeder too/)).toBeInTheDocument();
  });

  it("says a feeder with no birds this year has none, not that others saw them", async () => {
    fetchCompare.mockResolvedValue({
      ...COMPARE,
      feeders: [COMPARE.feeders[0], { ...COMPARE.feeders[1], species_year: 0 }],
      species: [COMPARE.species[0]],
    });
    render(<ComparePage go={() => {}} />);
    const dads = (await screen.findByRole("heading", { name: "Dad's" })).closest("article");
    expect(within(dads).getByText("No birds here yet this year.")).toBeInTheDocument();
    expect(within(dads).queryByText(/another feeder/)).toBeNull();
  });

  it("shows each first visit under its feeder and bolds the earliest", async () => {
    render(<ComparePage go={() => {}} />);
    const table = await screen.findByRole("table");
    const cardinal = within(table).getByRole("row", { name: /Northern Cardinal/ });
    const cells = within(cardinal).getAllByRole("cell");
    expect(cells).toHaveLength(2);
    expect(cells[1]).toHaveClass("compare-earliest");
    expect(cells[0]).not.toHaveClass("compare-earliest");
    const jay = within(table).getByRole("row", { name: /Blue Jay/ });
    expect(within(jay).getByLabelText("Not seen")).toBeInTheDocument();
  });

  it("opens History on a feeder", async () => {
    const go = vi.fn();
    render(<ComparePage go={go} />);
    const dads = (await screen.findByRole("heading", { name: "Dad's" })).closest("article");
    fireEvent.click(within(dads).getByRole("button", { name: "History" }));
    expect(go).toHaveBeenCalledWith("history", { device: 2 });
  });

  it("explains itself to a user with one feeder, without fetching", () => {
    mockData = { DEVICES: [HOME], ME: { id: 7, role: "viewer" } };
    render(<ComparePage go={() => {}} />);
    expect(screen.getByText("One feeder to compare")).toBeInTheDocument();
    expect(fetchCompare).not.toHaveBeenCalled();
  });

  it("says when no bird has come yet this year", async () => {
    fetchCompare.mockResolvedValue({ ...COMPARE, species: [] });
    render(<ComparePage go={() => {}} />);
    expect(await screen.findByText("No birds yet in 2026")).toBeInTheDocument();
  });
});
