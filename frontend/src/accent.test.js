import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  MIN_CONTRAST, SURFACES, accentStyle, baseAccent, contrast, fitAccent,
  onAccent, speciesAccent,
} from "./accent.js";

const css = readFileSync(join(process.cwd(), "src", "styles.css"), "utf8");

// Real seed palettes (backend/seed.py).
const HOUSE_FINCH = { palette: ["#bf6952", "#5e3530", "#d8c2a8"] };
const CHICKADEE = { palette: ["#1c2620", "#d4cdb8", "#7a6f5a"] };
const GOLDFINCH = { palette: ["#d4a23a", "#1c1810", "#8a6f1f"] };
const BLUE_JAY = { palette: ["#3f6e89", "#15263a", "#d4cdb8"] };
const HOUSE_SPARROW = { palette: [] }; // no palette in the seed

const SEEDS = [HOUSE_FINCH, CHICKADEE, GOLDFINCH, BLUE_JAY];

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

  it("has no base for an empty palette", () => {
    expect(baseAccent(HOUSE_SPARROW)).toBeNull();
    expect(speciesAccent(HOUSE_SPARROW)).toBeNull();
  });

  it("has no base for a missing species, a missing palette or a malformed colour", () => {
    expect(baseAccent(null)).toBeNull();
    expect(baseAccent({})).toBeNull();
    expect(baseAccent({ palette: ["not a colour"] })).toBeNull();
  });

  it("points an empty-palette species at the theme accent", () => {
    // It must still set the pair, or it would show the colour of a bird
    // further up the page, such as the latest visitor on the shell.
    const style = accentStyle(HOUSE_SPARROW);
    expect(style).toEqual(accentStyle(null));
    expect(style["--acc-day"]).toBe("var(--pal-acc)");
    expect(style["--acc-dusk"]).toBe("var(--pal-acc)");
    expect(style["--on-acc-day"]).toBe("var(--pal-on-acc)");
  });

  it("falls back to the theme accent in styles.css", () => {
    // An element with no bird above it has no --acc-day or --acc-dusk.
    expect(css).toContain("var(--acc-day, var(--pal-acc))");
    expect(css).toContain("var(--acc-dusk, var(--pal-acc))");
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

  it("makes every seed palette pass on every theme in both modes", () => {
    for (const sp of SEEDS) {
      const { day, dusk } = speciesAccent(sp);
      expect(passesEverywhere(day.acc, "day")).toBe(true);
      expect(passesEverywhere(dusk.acc, "dusk")).toBe(true);
    }
  });

  it("picks the text colour that reads on an accent fill", () => {
    for (const sp of SEEDS) {
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
