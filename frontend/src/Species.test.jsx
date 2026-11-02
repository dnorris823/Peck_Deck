import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("./api.js", () => ({ apiGet: vi.fn(), apiObjectUrl: vi.fn() }));

let mockData;
let mockFeeder = null;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: mockData, reload: vi.fn(), feeder: mockFeeder }),
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
    SCOPED_SIGHTINGS: [],
  };
}

// The life list answers per year. Tests set LIFE to a year's raw rows.
let LIFE;
function lifeList(path) {
  const year = new URLSearchParams(path.split("?")[1]).get("year");
  return { year: year && Number(year), years: Object.keys(LIFE.byYear).map(Number).sort((a, b) => b - a),
    species: (year ? LIFE.byYear[year] : LIFE.all) || [] };
}

function routeApi() {
  apiGet.mockImplementation((path) => {
    if (path.startsWith("/stats/hours")) return Promise.resolve(HOURS);
    if (path.startsWith("/stats/life-list")) return Promise.resolve(lifeList(path));
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
  mockFeeder = null;
  LIFE = { all: [], byYear: {} };
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
    expect(go).toHaveBeenCalledWith("history", { species: UNKNOWN.id, device: null });
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

describe("species scoped to one feeder", () => {
  const PORCH = { id: 11, name: "Dad's Porch" };

  it("opens History on the picked feeder from All N and Needs a name", async () => {
    setWide(true);
    setData([CARDINAL, UNKNOWN]);
    mockData.DEVICES = [DEVICE, PORCH];
    mockFeeder = 11;
    const go = vi.fn();
    render(<SpeciesPage go={go} openSighting={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^All 3,713/ }));
    expect(go).toHaveBeenLastCalledWith("history", { species: CARDINAL.id, device: 11 });
    await userEvent.click(screen.getByRole("button", { name: /Needs a name/ }));
    expect(go).toHaveBeenLastCalledWith("history", { species: UNKNOWN.id, device: 11 });
  });

  it("names the feeder and asks for its photos, visits and hours only", async () => {
    setWide(true);
    setData([CARDINAL]);
    mockData.DEVICES = [DEVICE, PORCH];
    mockFeeder = 11;
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    expect(screen.getByText("1 at Dad's Porch", { exact: false })).toBeInTheDocument();

    await waitFor(() => {
      const paths = apiGet.mock.calls.map(([p]) => p);
      expect(paths.some((p) => p.startsWith("/stats/hours"))).toBe(true);
      expect(paths.filter((p) => p.startsWith("/sightings")).length).toBeGreaterThan(0);
    });
    const paths = apiGet.mock.calls.map(([p]) => p);
    expect(paths.every((p) => p.includes("device_id=11"))).toBe(true);
  });
});

describe("life list and year list", () => {
  // Raw /stats/life-list rows, as the backend sends them.
  const raw = (id, common, count, first, extra = {}) => ({
    id, common_name: common, genus: "Genus", species_name: common.toLowerCase(), order_name: null,
    wiki_url: null, palette: [], silhouette: null, note: null, count,
    first_seen: first.toISOString(), last_seen: first.toISOString(), peak_hours: [],
    first_feeder_id: 10, first_feeder_name: "Backyard Maple", new_in_year: false, ...extra,
  });

  it("sorts by first seen, newest first", () => {
    const older = species(4, "Old Wren", 2, 60, { firstSeenAt: ago(60 * 24 * 400) });
    expect(sortSpecies([older, CARDINAL, FINCH], "first").map((s) => s.common))
      .toEqual(["House Finch", "Northern Cardinal", "Old Wren"]);
  });

  it("marks this year's new species and names the first feeder on the life list", async () => {
    setData([CARDINAL, FINCH, UNKNOWN]);
    LIFE = {
      all: [
        raw(2, "House Finch", 326, ago(60 * 24 * 3), { new_in_year: true }),
        raw(1, "Northern Cardinal", 3713, ago(60 * 24 * 90)),
      ],
      byYear: { 2025: [], 2026: [] },
    };
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    expect(await screen.findByText("New")).toBeInTheDocument();
    expect(screen.getByText("1 new this year", { exact: false })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "First seen" }));
    expect(screen.getAllByText(/^First seen .* at Backyard Maple/)).toHaveLength(2);
    // Unknown names no species, but it still waits for a name on all time.
    expect(rowNames()).toEqual(["Needs a name", "House FinchNew", "Northern Cardinal"]);
  });

  it("shows one year's birds when a year is picked, without Unknown", async () => {
    setData([CARDINAL, FINCH, UNKNOWN]);
    LIFE = {
      all: [],
      byYear: { 2025: [raw(1, "Northern Cardinal", 12, new Date(2025, 2, 1), { new_in_year: true })], 2026: [] },
    };
    render(<SpeciesPage go={vi.fn()} openSighting={vi.fn()} />);
    const picker = await screen.findByRole("combobox", { name: "Year" });
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["All time", "2026", "2025"]);

    await userEvent.selectOptions(picker, "2025");
    await screen.findByText("1 at your feeders in 2025", { exact: false });
    expect(apiGet).toHaveBeenCalledWith(expect.stringMatching(/^\/stats\/life-list\?tz=.*&year=2025$/));
    expect(rowNames()).toEqual(["Northern CardinalNew"]);
    expect(screen.getByText("1 new in 2025", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/^First seen Mar 1, 2025 at Backyard Maple/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();

    await userEvent.selectOptions(picker, "2026");
    expect(await screen.findByText("No birds at your feeders in 2026.")).toBeInTheDocument();
  });
});
