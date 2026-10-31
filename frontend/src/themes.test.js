import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MIN_CONTRAST, contrast } from "./color.js";
import { speciesAccent } from "./accent.js";
import {
  DEFAULT_PALETTE, NEUTRAL_ACCENT, PALETTES, SURFACES, isPalette, surfacesOf, themeTokens,
} from "./themes.js";

const css = readFileSync(join(process.cwd(), "src", "styles.css"), "utf8");
const MODES = ["day", "dusk"];
const TEXT = ["--fg", "--mu", "--pal-acc", "--ok", "--warn", "--bad", "--info"];

// The declarations in the first CSS block whose selector is exactly `selector`.
function block(selector) {
  const start = css.indexOf(`\n${selector} {`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(([, name, value]) => [name, value.trim()])
  );
}

describe("themes", () => {
  it("offers Peck Deck first, then T3 Code's five built-ins", () => {
    expect(PALETTES.map((p) => p.id)).toEqual(
      ["peck-deck", "orchid", "grove", "ocean", "ember", "iris"]
    );
    expect(PALETTES[0].id).toBe(DEFAULT_PALETTE);
  });

  it("sets the same tokens in every theme and mode", () => {
    const keys = Object.keys(themeTokens(DEFAULT_PALETTE, "day")).sort();
    for (const { id } of PALETTES) {
      for (const mode of MODES) expect(Object.keys(themeTokens(id, mode)).sort()).toEqual(keys);
    }
  });

  it("falls back to the default for an unknown id", () => {
    expect(isPalette("solarized")).toBe(false);
    expect(themeTokens("solarized", "day")).toBe(themeTokens(DEFAULT_PALETTE, "day"));
  });

  it("gives every text colour 4.5:1 on its own theme's surfaces", () => {
    for (const { id } of PALETTES) {
      for (const mode of MODES) {
        const t = themeTokens(id, mode);
        for (const name of TEXT) {
          for (const surface of surfacesOf(t)) {
            expect(contrast(t[name], surface), `${id} ${mode} ${name} on ${surface}`)
              .toBeGreaterThanOrEqual(MIN_CONTRAST);
          }
        }
        expect(contrast(t["--pal-on-acc"], t["--pal-acc"]), `${id} ${mode} on-accent`)
          .toBeGreaterThanOrEqual(MIN_CONTRAST);
      }
    }
  });

  it("fits a T3 Code accent that was only ever a fill colour", () => {
    // Orchid's dark accent is #a3004c, 2.16:1 on its own background.
    expect(themeTokens("orchid", "dusk")["--pal-acc"]).not.toBe("#a3004c");
  });

  it("collects every theme's surfaces for the species accent", () => {
    for (const { id } of PALETTES) {
      for (const mode of MODES) {
        for (const surface of surfacesOf(themeTokens(id, mode))) {
          expect(SURFACES[mode]).toContain(surface);
        }
      }
    }
  });

  it("makes a species accent read on every theme in both modes", () => {
    const { day, dusk } = speciesAccent({ palette: ["#d4a23a"] }); // goldfinch
    for (const { id } of PALETTES) {
      for (const s of surfacesOf(themeTokens(id, "day"))) {
        expect(contrast(day.acc, s)).toBeGreaterThanOrEqual(MIN_CONTRAST);
      }
      for (const s of surfacesOf(themeTokens(id, "dusk"))) {
        expect(contrast(dusk.acc, s)).toBeGreaterThanOrEqual(MIN_CONTRAST);
      }
    }
  });
});

describe("default palette in styles.css", () => {
  // styles.css paints the page before Appearance.jsx sets the tokens inline,
  // so its values must be the default palette's.
  it("matches themes.js in light mode", () => {
    const declared = block(":root");
    for (const [name, value] of Object.entries(themeTokens(DEFAULT_PALETTE, "day"))) {
      expect(declared[name], name).toBe(value);
    }
  });

  it("matches themes.js in dark mode", () => {
    const declared = block('[data-theme="dusk"]');
    for (const [name, value] of Object.entries(themeTokens(DEFAULT_PALETTE, "dusk"))) {
      expect(declared[name], name).toBe(value);
    }
  });

  it("keeps the stone grey for screens with no bird", () => {
    expect(themeTokens(DEFAULT_PALETTE, "day")["--pal-acc"]).toBe(NEUTRAL_ACCENT);
  });
});
