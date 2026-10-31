// Appearance — client-only visual preferences (colour theme, mode and density),
// persisted to localStorage. Both App (applies it) and Settings (edits it) read
// from this one context so changes are live and survive reload. A bird on
// screen still sets the accent colour (see accent.js). The theme sets it
// everywhere else.
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_PALETTE, isPalette, themeTokens } from "./themes.js";

const STORAGE_KEY = "peckdeck_appearance";

// `theme` is the light or dark mode. Settings labels it Mode, with Light and
// Dark. The key and the ids stay "theme", "day" and "dusk" so choices saved
// before colour themes existed still apply. `palette` is the colour theme.
export const DEFAULT_APPEARANCE = {
  theme: "auto",         // auto | day | dusk; auto follows the OS setting
  palette: DEFAULT_PALETTE,  // an id from PALETTES in themes.js
  density: "comfortable",    // compact | comfortable | spacious
};

// Density is expressed through the root font size (all layout uses rem-ish
// scaling off 14px), so it reads as a real, visible change.
const DENSITY_SCALE = { compact: 0.93, comfortable: 1, spacious: 1.07 };

export function loadAppearance() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      // Known keys only. Older builds also stored an accent and a display font.
      const saved = JSON.parse(raw);
      return {
        theme: saved.theme ?? DEFAULT_APPEARANCE.theme,
        palette: isPalette(saved.palette) ? saved.palette : DEFAULT_APPEARANCE.palette,
        density: saved.density ?? DEFAULT_APPEARANCE.density,
      };
    }
  } catch {
    /* ignore malformed/unavailable storage — fall back to defaults */
  }
  return { ...DEFAULT_APPEARANCE };
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

function resolveTheme(theme) {
  if (theme !== "auto") return theme;
  return window.matchMedia?.(DARK_QUERY).matches ? "dusk" : "day";
}

export function applyAppearance(a) {
  const root = document.documentElement;
  const mode = resolveTheme(a.theme);
  const tokens = themeTokens(a.palette, mode);
  root.dataset.theme = mode;
  root.dataset.palette = isPalette(a.palette) ? a.palette : DEFAULT_PALETTE;
  // Inline on <html>, so they beat the default palette in styles.css. Every
  // palette sets the same keys, so a switch overwrites the last one's.
  for (const [name, value] of Object.entries(tokens)) root.style.setProperty(name, value);
  root.style.fontSize = `${14 * (DENSITY_SCALE[a.density] || 1)}px`;
  // The phone status bar and the PWA title bar follow the page background.
  // Both tags in index.html get it, whatever their media query says.
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    meta.setAttribute("content", tokens["--bg"]);
  }
}

const Ctx = createContext(null);

export function AppearanceProvider({ children }) {
  const [appearance, setAppearance] = useState(loadAppearance);

  useEffect(() => {
    applyAppearance(appearance);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
    } catch {
      /* ignore storage write failures (private mode, quota) */
    }
  }, [appearance]);

  // On "auto", follow the OS when it flips between light and dark.
  useEffect(() => {
    if (appearance.theme !== "auto" || !window.matchMedia) return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => applyAppearance(appearance);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [appearance]);

  const value = useMemo(
    () => ({
      appearance,
      // Patch one or more fields at once.
      update: (patch) => setAppearance((a) => ({ ...a, ...patch })),
    }),
    [appearance]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppearance() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useAppearance must be used within AppearanceProvider");
  return ctx;
}
