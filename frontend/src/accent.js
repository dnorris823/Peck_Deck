// Species accent. The UI takes one accent colour, --acc, from the bird on
// screen: species.palette[0]. A species with no palette (many Pi-created ones,
// House Sparrow among them) gets a neutral accent instead.
//
// Accent text must reach 4.5:1 (WCAG AA) on every surface it can sit on, in both
// themes. A palette colour that misses is darkened for light mode and lightened
// for dark mode, hue and saturation kept, until it passes.
//
// How to use it: spread useSpeciesAccent(species) as the style of the element
// that shows that bird. Every descendant then reads var(--acc) and var(--on-acc).
// The hook sets one pair per theme (--acc-day, --acc-dusk), and styles.css picks
// the pair for the active theme on every element. That is why switching theme
// needs no re-render, and why nothing should set --acc directly.
import { useMemo } from "react";

export const MIN_CONTRAST = 4.5;

// Every surface accent text sits on, per theme. Mirrors --bg, --sheet and --chip
// in styles.css.
export const SURFACES = {
  day: ["#faf9f7", "#ffffff", "#f1eeea"],
  dusk: ["#0f0e0d", "#1a1917", "#201e1c"],
};

// Text on an accent fill is whichever of these reads better. Mirrors --fg.
const ON_LIGHT = "#151413";
const ON_DARK = "#ffffff";

// The fallback for a species without a palette, and for screens with no bird.
// A warm stone grey, so it reads as "no colour" rather than as a species.
export const NEUTRAL_ACCENT = "#6f6b66";

function parseHex(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex ?? "").trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function toHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}

function channel(v) {
  const c = v / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance of a hex colour, 0 to 1. */
export function luminance(hex) {
  const [r, g, b] = parseHex(hex).map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two hex colours, 1 to 21. */
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h / 6, s, l];
}

function hslToRgb([h, s, l]) {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const hue = (t) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [hue(h + 1 / 3) * 255, hue(h) * 255, hue(h - 1 / 3) * 255];
}

const worstContrast = (hex, surfaces) => Math.min(...surfaces.map((s) => contrast(hex, s)));

/**
 * The colour itself if it already reaches MIN_CONTRAST on every surface of the
 * theme. Otherwise the nearest lightness that does: darker for "day", lighter
 * for "dusk". Pure black and pure white pass on their theme's surfaces, so the
 * walk always ends.
 */
export function fitAccent(hex, theme) {
  const surfaces = SURFACES[theme];
  if (worstContrast(hex, surfaces) >= MIN_CONTRAST) return hex.toLowerCase();
  const [h, s, l] = rgbToHsl(parseHex(hex));
  const step = theme === "day" ? -0.01 : 0.01;
  for (let next = l + step; next >= 0 && next <= 1; next += step) {
    const candidate = toHex(hslToRgb([h, s, next]));
    if (worstContrast(candidate, surfaces) >= MIN_CONTRAST) return candidate;
  }
  return theme === "day" ? "#000000" : "#ffffff";
}

/** Text colour for a fill of `hex`: dark ink or white, whichever reads better. */
export function onAccent(hex) {
  return contrast(hex, ON_LIGHT) >= contrast(hex, ON_DARK) ? ON_LIGHT : ON_DARK;
}

/** The raw accent for a species: palette[0], or NEUTRAL_ACCENT without one. */
export function baseAccent(species) {
  const first = species?.palette?.[0];
  return parseHex(first) ? first : NEUTRAL_ACCENT;
}

/** Both themes' accent and on-accent colours for a species. */
export function speciesAccent(species) {
  const base = baseAccent(species);
  const day = fitAccent(base, "day");
  const dusk = fitAccent(base, "dusk");
  return {
    day: { acc: day, onAcc: onAccent(day) },
    dusk: { acc: dusk, onAcc: onAccent(dusk) },
  };
}

/** The CSS custom properties styles.css turns into --acc and --on-acc. */
export function accentStyle(species) {
  const { day, dusk } = speciesAccent(species);
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
  return useMemo(() => accentStyle({ palette: [base] }), [base]);
}
