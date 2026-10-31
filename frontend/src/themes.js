// Colour themes for the app shell. A theme is a palette with a light ("day")
// and a dark ("dusk") variant. The mode picks the variant, so Auto still
// follows the device.
//
// Peck Deck is the default, and its tokens are the hand-tuned values in
// styles.css. The other five are T3 Code's built-in themes, from
// packages/shared/src/themePalettes.ts, converted from OKLCH to hex. T3 Code
// defines a background, a foreground and an accent per variant. themeTokens()
// derives the rest of the shell tokens from those three.
//
// A theme only sets the accent where no bird is on screen. A bird's colour
// still wins wherever one is shown (see accent.js).
import { fitToSurfaces, mix, onAccent, rgba } from "./color.js";

export const DEFAULT_PALETTE = "peck-deck";

// The default palette's tokens. These mirror :root and [data-theme="dusk"] in
// styles.css, which paint the page before any script runs. themes.test.js
// checks the two match.
const PECK_DECK = {
  day: {
    "--bg": "#faf9f7",
    "--fg": "#151413",
    "--mu": "#6f6b66",
    "--line": "#ebe8e3",
    "--line-strong": "#d6d1ca",
    "--chip": "#f1eeea",
    "--sheet": "#ffffff",
    "--face": "#ffffff",
    "--night": "#f1eee9",
    "--hover": "rgba(21, 20, 19, 0.05)",
    "--glass": "rgba(250, 249, 247, 0.88)",
    "--ok": "#1d7a45",
    "--warn": "#85600f",
    "--bad": "#b3261e",
    "--info": "#33637f",
  },
  dusk: {
    "--bg": "#0f0e0d",
    "--fg": "#f4f2ef",
    "--mu": "#9d9891",
    "--line": "#282623",
    "--line-strong": "#3a3733",
    "--chip": "#201e1c",
    "--sheet": "#1a1917",
    "--face": "#1a1917",
    "--night": "#121110",
    "--hover": "rgba(244, 242, 239, 0.06)",
    "--glass": "rgba(15, 14, 13, 0.86)",
    "--ok": "#5fd08e",
    "--warn": "#e8bd5c",
    "--bad": "#f2877a",
    "--info": "#86b6d3",
  },
};

// The stone grey the default palette uses where no bird is on screen. It
// reads as "no colour" rather than as a species.
export const NEUTRAL_ACCENT = "#6f6b66";

// bg, fg and accent per variant. "Orchid" is T3 Code's t3-chat theme, renamed
// so Peck Deck does not carry another product's name.
const T3_CODE = {
  orchid: {
    label: "Orchid",
    day: ["#fdf7fd", "#501854", "#db2777"],
    dusk: ["#1f1a24", "#f9f8fb", "#a3004c"],
  },
  grove: {
    label: "Grove",
    day: ["#f3f7f4", "#241523", "#1b7d50"],
    dusk: ["#1b2821", "#fffaff", "#69d69a"],
  },
  ocean: {
    label: "Ocean",
    day: ["#f5f7f8", "#241523", "#2672af"],
    dusk: ["#17212b", "#fffaff", "#70b9ee"],
  },
  ember: {
    label: "Ember",
    day: ["#f9f7f5", "#241523", "#ae552a"],
    dusk: ["#291e1a", "#fffaff", "#f09a64"],
  },
  iris: {
    label: "Iris",
    day: ["#f8f7f9", "#241523", "#7253b9"],
    dusk: ["#1d1929", "#fffaff", "#9d7df2"],
  },
};

// How far each token sits from bg toward fg. Measured off the default palette,
// so a derived theme keeps its hierarchy of surfaces and lines.
const STEPS = {
  day: { sheet: null, chip: 0.045, night: 0.045, line: 0.065, lineStrong: 0.155, mu: 0.6, hover: 0.05, glass: 0.88 },
  dusk: { sheet: 0.048, chip: 0.074, night: 0.013, line: 0.109, lineStrong: 0.188, mu: 0.62, hover: 0.06, glass: 0.86 },
};

/** The surfaces text can sit on in a token set: --bg, --sheet and --chip. */
export const surfacesOf = (tokens) => [tokens["--bg"], tokens["--sheet"], tokens["--chip"]];

function derive([bg, fg], mode) {
  const s = STEPS[mode];
  const sheet = s.sheet == null ? "#ffffff" : mix(bg, fg, s.sheet);
  const chip = mix(bg, fg, s.chip);
  const surfaces = [bg, sheet, chip];
  // Text colours keep the default palette's hue, fitted to 4.5:1 here.
  const fit = (hex) => fitToSurfaces(hex, surfaces, mode === "dusk");
  const statuses = PECK_DECK[mode];
  return {
    "--bg": bg,
    "--fg": fg,
    "--mu": fit(mix(bg, fg, s.mu)),
    "--line": mix(bg, fg, s.line),
    "--line-strong": mix(bg, fg, s.lineStrong),
    "--chip": chip,
    "--sheet": sheet,
    "--face": sheet,
    "--night": mix(bg, fg, s.night),
    "--hover": rgba(fg, s.hover),
    "--glass": rgba(bg, s.glass),
    "--ok": fit(statuses["--ok"]),
    "--warn": fit(statuses["--warn"]),
    "--bad": fit(statuses["--bad"]),
    "--info": fit(statuses["--info"]),
  };
}

// The accent for screens with no bird, fitted to the palette's own surfaces.
// Some T3 Code accents are fill colours. Orchid's dark accent is 2.16:1 on
// its own background before fitting.
function withAccent(tokens, accent, mode) {
  const acc = fitToSurfaces(accent, surfacesOf(tokens), mode === "dusk");
  return { ...tokens, "--pal-acc": acc, "--pal-on-acc": onAccent(acc) };
}

function build() {
  const out = {
    [DEFAULT_PALETTE]: {
      label: "Peck Deck",
      day: withAccent(PECK_DECK.day, NEUTRAL_ACCENT, "day"),
      dusk: withAccent(PECK_DECK.dusk, NEUTRAL_ACCENT, "dusk"),
    },
  };
  for (const [id, { label, day, dusk }] of Object.entries(T3_CODE)) {
    out[id] = {
      label,
      day: withAccent(derive(day, "day"), day[2], "day"),
      dusk: withAccent(derive(dusk, "dusk"), dusk[2], "dusk"),
    };
  }
  return out;
}

const THEMES = build();

/** Theme ids and labels, in picker order. */
export const PALETTES = Object.entries(THEMES).map(([id, { label }]) => ({ id, label }));

export const isPalette = (id) => Object.hasOwn(THEMES, id);

/** Every shell token for a palette in a mode ("day" or "dusk"). */
export function themeTokens(palette, mode) {
  return (THEMES[palette] ?? THEMES[DEFAULT_PALETTE])[mode];
}

/**
 * Every surface accent text can sit on, per mode, across all palettes. The
 * species accent fits against all of them, so one --acc-day and --acc-dusk
 * pair per bird reads on every theme, and a theme switch needs no re-render.
 */
export const SURFACES = Object.fromEntries(
  ["day", "dusk"].map((mode) => [
    mode,
    [...new Set(Object.values(THEMES).flatMap((t) => surfacesOf(t[mode])))],
  ])
);
