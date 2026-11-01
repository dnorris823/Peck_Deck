import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("./api.js", () => ({ apiGet: vi.fn(), apiObjectUrl: vi.fn() }));

let mockData;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: mockData, reload: vi.fn() }),
}));

import { apiGet } from "./api.js";
import { SpeciesPage, sortSpecies } from "./Species.jsx";

const ago = (mins) => new Date(Date.now() - mins * 60000);

function species(id, common, count, lastMinsAgo, extra = {}) {
  return {
    id, common, sci: `Genus ${common.toLowerCase()}`, order: "—", palette: ["#c8412c"],
    silhouette: "songbird", wiki: null, note: "", count, firstSeen: "",
    firstSeenAt: ago(60 * 24 * 90), lastSeenAt: ago(lastMinsAgo), peakHours: [8, 17], ...extra,
  };
}

const CARDINAL = species(1, "Northern Cardinal", 3713, 60 * 24);
const FINCH = species(2, "House Finch", 326, 11, { peakHours: [18] });
const UNKNOWN = species(3, "Unknown", 1, 300, { peakHours: [] });
const DEVICE = { id: 10, name: "Backyard Maple" };

const HOURS = {
  counts: Array.from({ length: 24 }, (_, h) => (h === 8 ? 5 : h === 17 ? 3 : 0)),
  total: 8, peak_hours: [8, 17], earliest: "05:20", latest: "19:58",
};

function setData(counts) {
  mockData = {
    SPECIES_COUNTS: counts,
    SPECIES: counts,
    DEVICES: [DEVICE],
    SIGHTINGS: [],
  };
}

function routeApi() {
  apiGet.mockImplementation((path) => {
    if (path.startsWith("/stats/hours")) return Promise.resolve(HOURS);
    if (path.startsWith("/sightings")) {
      const id = Number(new URLSearchParams(path.split("?")[1]).get("species_id"));
      return Promise.resolve([
        { id: 500 + id, species_id: id, device_id: 10, datetime: ago(30).toISOString(),
          confidence_score: 0.9, classification_tier_used: "gpu", has_image: false },
      ]);
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function setWide(wide) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: wide, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.scrollTo = vi.fn();
  routeApi();
  setWide(false);
});

afterEach(() => {
  delete window.matchMedia;
});

const rowNames = () =>
  within(screen.getByRole("navigation", { name: "Species" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".sp-name").textContent);

describe("species list", () => {
  it("sorts by recent, most seen and A to Z", () => {
    const list = [CARDINAL, FINCH];
    expect(sortSpecies(list, "recent").map((s) => s.common)).toEqual(["House Finch", "Northern Cardinal"]);
    expect(sortSpecies(list, "count").map((s) => s.common)).toEqual(["Northern Cardinal", "House Finch"]);
    expect(sortSpecies(list, "name").map((s) => s.common)).toEqual(["House Finch", "Northern Cardinal"]);
  });

  it("shows when each bird usually comes, and its last visit", async () => {
    setData([CARDINAL, FINCH]);
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    expect(rowNames()).toEqual(["House Finch", "Northern Cardinal"]);
    expect(screen.getByText("8 am, 5 pm")).toBeInTheDocument();
    expect(screen.getByText("evenings")).toBeInTheDocument();
    expect(screen.getByText(/11 min ago/)).toBeInTheDocument();
    expect(screen.getByText("2 at your feeders", { exact: false })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Most seen" }));
    expect(rowNames()).toEqual(["Northern Cardinal", "House Finch"]);
  });

  it("puts Needs a name on top only when an Unknown sighting exists", async () => {
    const go = vi.fn();
    setData([CARDINAL, UNKNOWN, FINCH]);
    const { unmount } = render(<SpeciesPage go={go} openSighting={vi.fn()} />);
    expect(rowNames()).toEqual(["Needs a name", "House Finch", "Northern Cardinal"]);
    // Unknown is not a species, so it is not counted as one.
    expect(screen.getByText("2 at your feeders", { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Needs a name/ }));
    expect(go).toHaveBeenCalledWith("history", { species: UNKNOWN.id });
    unmount();

    setData([CARDINAL, FINCH]);
    render(<SpeciesPage go={go} openSighting={vi.fn()} />);
    expect(screen.queryByText("Needs a name")).not.toBeInTheDocument();
  });
});

describe("species page", () => {
  it("opens from the list on a phone, with a dial in the browser's zone", async () => {
    const openSighting = vi.fn();
    setData([CARDINAL, FINCH]);
    render(<SpeciesPage go={vi.fn()} openSighting={openSighting} />);
    await userEvent.click(screen.getByRole("button", { name: /Northern Cardinal/ }));

    const page = screen.getByRole("article", { name: "Northern Cardinal" });
    expect(screen.queryByRole("navigation", { name: "Species" })).not.toBeInTheDocument();
    expect(within(page).getByText("3,713")).toBeInTheDocument();

    const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
    await waitFor(() => expect(within(page).getByText("5:20 am · 7:58 pm")).toBeInTheDocument());
    expect(apiGet).toHaveBeenCalledWith(`/stats/hours?species_id=1&days=30&tz=${zone}`);
    expect(within(page).getByText("8 am")).toBeInTheDocument();
    expect(within(page).getByText("5 pm")).toBeInTheDocument();

    await userEvent.click(within(page).getByRole("button", { name: "All time" }));
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith(`/stats/hours?species_id=1&days=0&tz=${zone}`));

    const visit = await within(page).findByRole("button", { name: /^Northern Cardinal, / });
    await userEvent.click(visit);
    expect(openSighting).toHaveBeenCalledWith(expect.objectContaining({ id: 501, device: DEVICE }));

    await userEvent.click(within(page).getByRole("button", { name: "‹ Species" }));
    expect(screen.getByRole("navigation", { name: "Species" })).toBeInTheDocument();
  });

  it("sits beside the list on a wide screen, showing the top row", async () => {
    setWide(true);
    setData([CARDINAL, FINCH]);
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    expect(screen.getByRole("navigation", { name: "Species" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "House Finch" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "‹ Species" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Northern Cardinal/ }));
    expect(screen.getByRole("article", { name: "Northern Cardinal" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Species" });
    expect(within(nav).getByRole("button", { name: /Northern Cardinal/ })).toHaveAttribute("aria-current", "true");
    await screen.findByText("5:20 am · 7:58 pm");
  });

  it("links out to Wikipedia, eBird, All About Birds and Xeno-canto", async () => {
    setWide(true);
    setData([species(1, "Blue Jay", 40, 60, {
      wiki: "https://en.wikipedia.org/wiki/Blue_jay", ebird: "blujay",
    })]);
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    const more = screen.getByRole("region", { name: "Learn more" });
    const hrefs = within(more).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      "https://en.wikipedia.org/wiki/Blue_jay",
      "https://ebird.org/species/blujay",
      "https://www.allaboutbirds.org/guide/blujay",
      "https://xeno-canto.org/explore?query=Blue%20Jay",
    ]);
    await screen.findByText("5:20 am · 7:58 pm");
  });
});
