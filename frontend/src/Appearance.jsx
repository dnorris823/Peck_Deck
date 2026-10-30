// Appearance — client-only visual preferences (theme and density), persisted
// to localStorage. Both App (applies it) and Settings (edits it) read from this
// one context so changes are live and survive reload. The accent colour is not
// a preference: it comes from the bird on screen (see accent.js).
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "peckdeck_appearance";

// Settings labels the themes Light and Dark. The ids stay "day" and "dusk" so
// choices saved before the redesign still apply.
export const DEFAULT_APPEARANCE = {
  theme: "auto",         // auto | day | dusk; auto follows the OS setting
  density: "comfortable",    // compact | comfortable | spacious
};

// Density is expressed through the root font size (all layout uses rem-ish
// scaling off 14px), so it reads as a real, visible change.
const DENSITY_SCALE = { compact: 0.93, comfortable: 1, spacious: 1.07 };

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      // Known keys only. Older builds also stored an accent and a display font.
      const saved = JSON.parse(raw);
      return {
        theme: saved.theme ?? DEFAULT_APPEARANCE.theme,
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
  root.dataset.theme = resolveTheme(a.theme);
  root.style.fontSize = `${14 * (DENSITY_SCALE[a.density] || 1)}px`;
}

const Ctx = createContext(null);

export function AppearanceProvider({ children }) {
  const [appearance, setAppearance] = useState(load);

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
