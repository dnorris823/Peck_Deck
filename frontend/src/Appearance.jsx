// Appearance — client-only visual preferences (theme/accent/font/density),
// persisted to localStorage. Both App (applies it) and Settings (edits it)
// read from this one context so changes are live and survive reload.
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "peckdeck_appearance";

// `showLiveAlerts` isn't surfaced in Settings yet, but lives here so all
// appearance state has a single home.
export const DEFAULT_APPEARANCE = {
  theme: "day",          // day | dusk
  accent: "cardinal",    // cardinal | forest | yolk | plum
  displayFont: "newsreader", // newsreader | instrument | playfair | eb
  density: "comfortable",    // compact | comfortable | spacious
  showLiveAlerts: true,
};

const ACCENTS = {
  cardinal: { primary: "#b8412c", deep: "#8a2f1e" },
  forest: { primary: "#2d4a36", deep: "#1d3225" },
  yolk: { primary: "#d4a23a", deep: "#a37a1f" },
  plum: { primary: "#6b4570", deep: "#4a2f51" },
};

const FONTS = {
  newsreader: '"Newsreader", "Times New Roman", serif',
  instrument: '"Instrument Serif", "Times New Roman", serif',
  playfair: '"Playfair Display", "Times New Roman", serif',
  eb: '"EB Garamond", "Times New Roman", serif',
};

// Density is expressed through the root font size (all layout uses rem-ish
// scaling off 14px), so it reads as a real, visible change.
const DENSITY_SCALE = { compact: 0.93, comfortable: 1, spacious: 1.07 };

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_APPEARANCE, ...JSON.parse(raw) };
  } catch {
    /* ignore malformed/unavailable storage — fall back to defaults */
  }
  return { ...DEFAULT_APPEARANCE };
}

export function applyAppearance(a) {
  const root = document.documentElement;
  root.dataset.theme = a.theme;
  const accent = ACCENTS[a.accent] || ACCENTS.cardinal;
  root.style.setProperty("--cardinal", accent.primary);
  root.style.setProperty("--cardinal-deep", accent.deep);
  root.style.setProperty("--display", FONTS[a.displayFont] || FONTS.newsreader);
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
