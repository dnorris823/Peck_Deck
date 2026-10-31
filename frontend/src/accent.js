// Species accent. The UI takes one accent colour, --acc, from the bird on
// screen: species.palette[0]. A species with no palette (many Pi-created ones,
// House Sparrow among them) takes the theme's accent instead, as does a screen
// with no bird.
//
// Accent text must reach 4.5:1 (WCAG AA) on every surface it can sit on, in
// both modes and every theme. A palette colour that misses is darkened for
// light mode and lightened for dark mode, hue and saturation kept, until it
// passes.
//
// How to use it: spread useSpeciesAccent(species) as the style of the element
// that shows that bird. Every descendant then reads var(--acc) and var(--on-acc).
// The hook sets one pair per mode (--acc-day, --acc-dusk), and styles.css picks
// the pair for the active mode on every element. That is why switching mode or
// theme needs no re-render, and why nothing should set --acc directly.
import { useMemo } from "react";
import { fitToSurfaces, onAccent, parseHex } from "./color.js";
import { SURFACES } from "./themes.js";

export { MIN_CONTRAST, contrast, luminance, onAccent } from "./color.js";
export { SURFACES };

/**
 * The colour itself if it already reaches 4.5:1 on every surface of the mode,
 * in every theme. Otherwise the nearest lightness that does: darker for "day",
 * lighter for "dusk".
 */
export function fitAccent(hex, mode) {
  return fitToSurfaces(hex, SURFACES[mode], mode === "dusk");
}

/** The raw accent for a species: palette[0], or null without one. */
export function baseAccent(species) {
  const first = species?.palette?.[0];
  return parseHex(first) ? first : null;
}

/** Both modes' accent and on-accent colours for a species, or null without a palette. */
export function speciesAccent(species) {
  const base = baseAccent(species);
  if (base == null) return null;
  const day = fitAccent(base, "day");
  const dusk = fitAccent(base, "dusk");
  return {
    day: { acc: day, onAcc: onAccent(day) },
    dusk: { acc: dusk, onAcc: onAccent(dusk) },
  };
}

// A bird with no palette shows the theme accent. It still sets the pair, so it
// overrides the accent of a bird further up the page. --pal-acc is already the
// active mode's, set by Appearance.jsx.
const THEME_ACCENT = {
  "--acc-day": "var(--pal-acc)",
  "--on-acc-day": "var(--pal-on-acc)",
  "--acc-dusk": "var(--pal-acc)",
  "--on-acc-dusk": "var(--pal-on-acc)",
};

/** The CSS custom properties styles.css turns into --acc and --on-acc. */
export function accentStyle(species) {
  const fitted = speciesAccent(species);
  if (fitted == null) return THEME_ACCENT;
  const { day, dusk } = fitted;
  return {
    "--acc-day": day.acc,
    "--on-acc-day": day.onAcc,
    "--acc-dusk": dusk.acc,
    "--on-acc-dusk": dusk.onAcc,
  };
}

/** accentStyle, memoised on the palette colour. Spread it into a style prop. */
export function useSpeciesAccent(species) {
  const base = baseAccent(species);
  return useMemo(() => accentStyle(base == null ? null : { palette: [base] }), [base]);
}
