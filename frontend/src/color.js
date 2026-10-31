// Colour maths shared by the species accent (accent.js) and the themes
// (themes.js). Hex in, hex out, sRGB throughout.

export const MIN_CONTRAST = 4.5;

export function parseHex(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex ?? "").trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

export function toHex([r, g, b]) {
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

/** `a` moved a fraction `t` of the way toward `b`, per sRGB channel. */
export function mix(a, b, t) {
  const [x, y] = [parseHex(a), parseHex(b)];
  return toHex(x.map((v, i) => v + (y[i] - v) * t));
}

/** "rgba(r, g, b, alpha)" for a hex colour. */
export function rgba(hex, alpha) {
  return `rgba(${parseHex(hex).join(", ")}, ${alpha})`;
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

export const worstContrast = (hex, surfaces) =>
  Math.min(...surfaces.map((s) => contrast(hex, s)));

/**
 * The colour itself if it already reaches MIN_CONTRAST on every surface.
 * Otherwise the nearest lightness that does, hue and saturation kept: darker
 * when `lighten` is false, lighter when it is true. Pure black passes on light
 * surfaces and pure white on dark ones, so the walk always ends.
 */
export function fitToSurfaces(hex, surfaces, lighten) {
  if (worstContrast(hex, surfaces) >= MIN_CONTRAST) return hex.toLowerCase();
  const [h, s, l] = rgbToHsl(parseHex(hex));
  const step = lighten ? 0.01 : -0.01;
  for (let next = l + step; next >= 0 && next <= 1; next += step) {
    const candidate = toHex(hslToRgb([h, s, next]));
    if (worstContrast(candidate, surfaces) >= MIN_CONTRAST) return candidate;
  }
  return lighten ? "#ffffff" : "#000000";
}

// Text on a fill is whichever of these reads better. Mirrors --fg.
const ON_LIGHT = "#151413";
const ON_DARK = "#ffffff";

/** Text colour for a fill of `hex`: dark ink or white, whichever reads better. */
export function onAccent(hex) {
  return contrast(hex, ON_LIGHT) >= contrast(hex, ON_DARK) ? ON_LIGHT : ON_DARK;
}
