import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  MIN_CONTRAST, NEUTRAL_ACCENT, SURFACES, accentStyle, baseAccent, contrast, fitAccent,
  onAccent, speciesAccent,
} from "./accent.js";

const css = readFileSync(join(process.cwd(), "src", "styles.css"), "utf8");

// Real seed palettes (backend/seed.py).
const HOUSE_FINCH = { palette: ["#bf6952", "#5e3530", "#d8c2a8"] };
const CHICKADEE = { palette: ["#1c2620", "#d4cdb8", "#7a6f5a"] };
const GOLDFINCH = { palette: ["#d4a23a", "#1c1810", "#8a6f1f"] };
const BLUE_JAY = { palette: ["#3f6e89", "#15263a", "#d4cdb8"] };
const HOUSE_SPARROW = { palette: [] }; // no palette in the seed

const passesEverywhere = (hex, theme) =>
  SURFACES[theme].every((surface) => contrast(hex, surface) >= MIN_CONTRAST);

describe("contrast", () => {
  it("matches the WCAG reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // #767676 on white is the textbook just-passing AA grey.
    expect(contrast("#767676", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#777777", "#ffffff")).toBeLessThan(4.5);
  });
});

describe("accent fallback", () => {
  it("uses palette[0] when the species has one", () => {
    expect(baseAccent(HOUSE_FINCH)).toBe("#bf6952");
  });

  it("falls back to the neutral accent for an empty palette", () => {
    expect(baseAccent(HOUSE_SPARROW)).toBe(NEUTRAL_ACCENT);
  });

  it("falls back for a missing species, a missing palette or a malformed colour", () => {
    expect(baseAccent(null)).toBe(NEUTRAL_ACCENT);
    expect(baseAccent({})).toBe(NEUTRAL_ACCENT);
    expect(baseAccent({ palette: ["not a colour"] })).toBe(NEUTRAL_ACCENT);
  });

  it("gives an empty-palette species the same accent as no species", () => {
    expect(speciesAccent(HOUSE_SPARROW)).toEqual(speciesAccent(null));
  });

  it("matches the neutral defaults hard-coded in styles.css", () => {
    // The stylesheet holds the accent for screens with no bird, before any
    // inline style applies. It must be the neutral accent, already fitted.
    const { day, dusk } = speciesAccent(null);
    expect(css).toContain(`var(--acc-day, ${day.acc})`);
    expect(css).toContain(`var(--on-acc-day, ${day.onAcc})`);
    expect(css).toContain(`var(--acc-dusk, ${dusk.acc})`);
    expect(css).toContain(`var(--on-acc-dusk, ${dusk.onAcc})`);
  });
});

describe("contrast adjustment", () => {
  it("leaves a colour alone when it already passes", () => {
    expect(fitAccent("#3f6e89", "day")).toBe(BLUE_JAY.palette[0]);
  });

  it("darkens a light-theme failure until it passes", () => {
    // House Finch is 3.7:1 on the light background.
    expect(passesEverywhere("#bf6952", "day")).toBe(false);
    const fitted = fitAccent("#bf6952", "day");
    expect(passesEverywhere(fitted, "day")).toBe(true);
    expect(contrast(fitted, "#ffffff")).toBeGreaterThan(contrast("#bf6952", "#ffffff"));
  });

  it("lightens a dark-theme failure until it passes", () => {
    // Chickadee black is close to invisible on the dark background.
    expect(passesEverywhere("#1c2620", "dusk")).toBe(false);
    const fitted = fitAccent("#1c2620", "dusk");
    expect(passesEverywhere(fitted, "dusk")).toBe(true);
    expect(contrast(fitted, "#000000")).toBeGreaterThan(contrast("#1c2620", "#000000"));
  });

  it("changes lightness only, keeping the hue", () => {
    const fitted = fitAccent("#d4a23a", "day");
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(fitted.slice(i, i + 2), 16));
    // Goldfinch stays yellow-orange: red over green over blue.
    expect(r).toBeGreaterThan(g);
    expect(g).toBeGreaterThan(b);
  });

  it("makes every seed palette and the neutral pass in both themes", () => {
    for (const sp of [HOUSE_FINCH, CHICKADEE, GOLDFINCH, BLUE_JAY, HOUSE_SPARROW]) {
      const { day, dusk } = speciesAccent(sp);
      expect(passesEverywhere(day.acc, "day")).toBe(true);
      expect(passesEverywhere(dusk.acc, "dusk")).toBe(true);
    }
  });

  it("picks the text colour that reads on an accent fill", () => {
    for (const sp of [HOUSE_FINCH, CHICKADEE, GOLDFINCH, BLUE_JAY, HOUSE_SPARROW]) {
      const { day, dusk } = speciesAccent(sp);
      expect(contrast(day.onAcc, day.acc)).toBeGreaterThanOrEqual(MIN_CONTRAST);
      expect(contrast(dusk.onAcc, dusk.acc)).toBeGreaterThanOrEqual(MIN_CONTRAST);
    }
    expect(onAccent("#ffffff")).toBe("#151413");
    expect(onAccent("#000000")).toBe("#ffffff");
  });
});

describe("accentStyle", () => {
  it("sets one accent pair per theme", () => {
    const style = accentStyle(HOUSE_FINCH);
    expect(Object.keys(style).sort()).toEqual(
      ["--acc-day", "--acc-dusk", "--on-acc-day", "--on-acc-dusk"]
    );
    expect(style["--acc-day"]).not.toBe(style["--acc-dusk"]);
  });
});
