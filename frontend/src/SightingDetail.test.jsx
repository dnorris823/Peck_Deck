// The sighting detail view: the delete button and its confirm step, the accent,
// the tiers row with and without a trace, the day's strip, and the helpers
// behind the context line.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const applyDeleted = vi.fn();
let me;
let sightings;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({ data: { SPECIES_COUNTS: [], ME: me, SIGHTINGS: sightings }, applyDeleted }),
}));

vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  deleteSighting: vi.fn(),
  fetchSpeciesHours: vi.fn(),
}));

import { deleteSighting, fetchSpeciesHours } from "./data.js";
import {
  SightingDetail, canDeleteSighting, dayStrip, visitOrdinal, ordinal, busyPhrase,
  contextLine, tierChips, thresholdFor,
} from "./SightingDetail.jsx";
import { speciesAccent } from "./accent.js";

const SQUIRREL = {
  id: 1, common: "Gray Squirrel", sci: "Sciurus carolinensis",
  palette: ["#777", "#333", "#ccc"], silhouette: "songbird",
};
const UNKNOWN = { id: 9, common: "Unknown", sci: "", palette: [], silhouette: "songbird" };
const WINDOW = { id: 4, name: "Window", ownerId: 7 };
const PORCH = { id: 5, name: "Porch", ownerId: 7 };

const S = {
  id: 12,
  species: SQUIRREL,
  device: WINDOW,
  datetime: new Date("2026-10-29T12:00:00Z"),
  confidence: 0.9,
  tier: "gpu",
  hasImage: false,
  delayed: false,
  tierTrace: null,
};

// Visits on one local day, newest first like data.SIGHTINGS.
function at(hour, extra = {}) {
  const d = new Date(2026, 9, 28, hour, 0, 0);
  return { ...S, id: 100 + hour, datetime: d, ...extra };
}

beforeEach(() => {
  vi.clearAllMocks();
  me = { id: 7, role: "viewer" };
  sightings = [];
  fetchSpeciesHours.mockResolvedValue({ peak_hours: [] });
});

describe("canDeleteSighting", () => {
  it("lets the device owner delete, whatever their role", () => {
    expect(canDeleteSighting(S, { id: 7, role: "viewer" })).toBe(true);
  });

  it("lets an owner-role user delete on any device", () => {
    expect(canDeleteSighting(S, { id: 8, role: "owner" })).toBe(true);
  });

  it("hides it from a viewer who doesn't own the device", () => {
    expect(canDeleteSighting(S, { id: 8, role: "viewer" })).toBe(false);
  });
});

describe("delete button", () => {
  it("asks for confirmation before deleting", async () => {
    deleteSighting.mockResolvedValue(null);
    const onClose = vi.fn();
    render(<SightingDetail s={S} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteSighting).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete this sighting" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(deleteSighting).toHaveBeenCalledWith(12);
    expect(applyDeleted).toHaveBeenCalledWith(12);
  });

  it("keeps the view open and says why when the delete fails", async () => {
    deleteSighting.mockRejectedValue(new Error("Request to /sightings/12 failed (403)."));
    const onClose = vi.fn();
    render(<SightingDetail s={S} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete this sighting" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("403");
    expect(onClose).not.toHaveBeenCalled();
    expect(applyDeleted).not.toHaveBeenCalled();
  });

  it("is absent for a viewer who doesn't own the device", () => {
    me = { id: 8, role: "viewer" };
    render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("accent", () => {
  const accentOf = () => screen.getByRole("dialog").style.getPropertyValue("--acc-day");

  it("takes the accent from the sighting's species", () => {
    render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(accentOf()).toBe(speciesAccent(S.species).day.acc);
  });

  it("falls back to the neutral accent for a species with no palette", () => {
    const sparrow = { ...S, species: { ...S.species, palette: [] } };
    render(<SightingDetail s={sparrow} onClose={vi.fn()} />);
    expect(accentOf()).toBe(speciesAccent(null).day.acc);
  });
});

describe("header and details", () => {
  it("names an Unknown capture 'Needs a name' and skips the busy hours", () => {
    render(<SightingDetail s={{ ...S, species: UNKNOWN, tier: "none", confidence: 0 }} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Needs a name" })).toBeInTheDocument();
    expect(screen.getByText("No tier answered")).toBeInTheDocument();
    expect(fetchSpeciesHours).not.toHaveBeenCalled();
  });

  it("treats Tier 1's old Background class as unnamed too", () => {
    const background = { ...UNKNOWN, common: "Background" };
    render(<SightingDetail s={{ ...S, species: background, tier: "local" }} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Needs a name" })).toBeInTheDocument();
    // 90% sure of "Background" is not a name, so no tick.
    expect(screen.getByText("Pi, no name")).toBeInTheDocument();
  });

  it("shows the tier that answered and its confidence without a trace", () => {
    render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(screen.getByText("GPU ✓")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
  });

  it("says whether the upload was live or queued", () => {
    const { rerender } = render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(screen.getByText("Live, not queued")).toBeInTheDocument();
    rerender(<SightingDetail s={{ ...S, delayed: true }} onClose={vi.fn()} />);
    expect(screen.getByText("Queued, sent later")).toBeInTheDocument();
  });

  it("adds the busy hours to the context line", async () => {
    fetchSpeciesHours.mockResolvedValue({ peak_hours: [17, 18] });
    render(<SightingDetail s={S} onClose={vi.fn()} />);
    expect(await screen.findByText(/Busiest 5 to 7 pm/)).toBeInTheDocument();
    expect(fetchSpeciesHours).toHaveBeenCalledWith(1);
  });
});

describe("tierChips", () => {
  it("reads the trace in chain order and marks a tier outside the chain as off", () => {
    const s = {
      ...S, tier: "gpu", confidence: 0.71,
      tierTrace: [
        { tier: "gpu", outcome: "accepted", confidence: 0.71, threshold: 0.6 },
        { tier: "local", outcome: "not_run", confidence: null, threshold: 0.85 },
      ],
    };
    expect(tierChips(s).map(c => [c.label, c.state])).toEqual([
      ["GPU ✓", "ok"], ["Pi skipped", "off"], ["Claude off", "off"],
    ]);
  });

  it("shows a below-bar score and a failure", () => {
    const s = {
      ...S, tier: "local", confidence: 0.41,
      tierTrace: [
        { tier: "gpu", outcome: "failed", confidence: null, threshold: 0.6 },
        { tier: "local", outcome: "below_threshold", confidence: 0.41, threshold: 0.85 },
      ],
    };
    expect(tierChips(s).map(c => [c.label, c.state])).toEqual([
      ["GPU failed", "off"], ["Pi 41%", "low"], ["Claude off", "off"],
    ]);
  });

  it("flags an unsure answer when there is no trace", () => {
    expect(tierChips({ ...S, tier: "local", confidence: 0.7 })).toEqual([
      { tier: "local", label: "Pi 70%", state: "low" },
    ]);
  });
});

describe("thresholdFor", () => {
  it("prefers the bar the Pi reported", () => {
    const s = { ...S, tierTrace: [{ tier: "gpu", outcome: "accepted", confidence: 0.9, threshold: 0.7 }] };
    expect(thresholdFor(s)).toBe(0.7);
  });

  it("falls back to the default bar, and has none for no tier", () => {
    expect(thresholdFor(S)).toBe(0.6);
    expect(thresholdFor({ ...S, tier: "none" })).toBeNull();
  });
});

describe("the day's strip", () => {
  it("holds the same feeder's visits that day, newest first", () => {
    const list = [at(18), at(15, { device: PORCH }), at(12), at(9)];
    sightings = list;
    expect(dayStrip(list, list[2]).map(x => x.id)).toEqual([118, 112, 109]);
  });

  it("includes a sighting fetched from outside the loaded list", () => {
    const outside = { ...S, id: 5 };
    expect(dayStrip([at(9)], outside).map(x => x.id)).toEqual([5]);
  });

  it("moves with the arrow keys and the strip", () => {
    const list = [at(18), at(12), at(9)];
    sightings = list;
    const onMove = vi.fn();
    render(<SightingDetail s={list[1]} onClose={vi.fn()} onMove={onMove} />);

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(onMove).toHaveBeenLastCalledWith(list[0]);
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onMove).toHaveBeenLastCalledWith(list[2]);

    fireEvent.click(screen.getByRole("button", { name: /9:00/ }));
    expect(onMove).toHaveBeenLastCalledWith(list[2]);
  });

  it("moves with a horizontal swipe on the photo", () => {
    const list = [at(18), at(12), at(9)];
    sightings = list;
    const onMove = vi.fn();
    const { container } = render(<SightingDetail s={list[1]} onClose={vi.fn()} onMove={onMove} />);
    const photo = container.querySelector(".sd-photo");

    fireEvent.touchStart(photo, { touches: [{ clientX: 200, clientY: 100 }] });
    fireEvent.touchEnd(photo, { changedTouches: [{ clientX: 100, clientY: 110 }] });
    expect(onMove).toHaveBeenLastCalledWith(list[2]);
  });

  it("stops at the ends", () => {
    const list = [at(18), at(12)];
    sightings = list;
    const onMove = vi.fn();
    render(<SightingDetail s={list[0]} onClose={vi.fn()} onMove={onMove} />);
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(onMove).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Newer visit" })).toBeDisabled();
  });
});

describe("context line", () => {
  it("counts this species' visits that day up to this one", () => {
    const finch = { ...SQUIRREL, id: 2, common: "House Finch" };
    const list = [at(18), at(15, { species: finch }), at(12), at(9)];
    expect(visitOrdinal(list, list[0])).toBe(3);
    expect(visitOrdinal(list, list[3])).toBe(1);
  });

  it("gives no count when the loaded window may not reach the day's start", () => {
    const full = Array.from({ length: 100 }, (_, i) => at(23, { id: 1000 + i }));
    expect(visitOrdinal(full, full[0])).toBeNull();
  });

  it("writes ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101].map(ordinal))
      .toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]);
  });

  it("writes peak hours as a span or as two times", () => {
    expect(busyPhrase([17, 18])).toBe("5 to 7 pm");
    expect(busyPhrase([18, 17])).toBe("5 to 7 pm");
    expect(busyPhrase([11, 12])).toBe("11 am to 1 pm");
    expect(busyPhrase([23, 0])).toBe("11 pm to 1 am");
    expect(busyPhrase([7])).toBe("7 to 8 am");
    expect(busyPhrase([17, 7])).toBe("around 7 am and 5 pm");
    expect(busyPhrase([])).toBeNull();
  });

  it("joins the count and the busy hours", () => {
    const s = at(12);
    const now = new Date(2026, 9, 28, 20, 0, 0);
    expect(contextLine(s, 5, [17, 18], now)).toBe("5th visit today. Busiest 5 to 7 pm over the last 30 days.");
    expect(contextLine(s, 2, null, new Date(2026, 9, 29, 8))).toBe("2nd visit yesterday.");
    expect(contextLine(s, null, null, now)).toBe("");
  });
});
