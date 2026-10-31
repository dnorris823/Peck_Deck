import { describe, it, expect, beforeEach } from "vitest";
import { applyAppearance, loadAppearance } from "./Appearance.jsx";
import { themeTokens } from "./themes.js";

const KEY = "peckdeck_appearance";

beforeEach(() => {
  localStorage.clear();
  document.head.innerHTML = `
    <meta name="theme-color" content="#faf9f7" media="(prefers-color-scheme: light)" />
    <meta name="theme-color" content="#0f0e0d" media="(prefers-color-scheme: dark)" />`;
  document.documentElement.removeAttribute("style");
});

describe("loadAppearance", () => {
  it("loads a choice saved before themes existed as the default theme", () => {
    localStorage.setItem(KEY, JSON.stringify({ theme: "dusk", density: "compact" }));
    expect(loadAppearance()).toEqual({ theme: "dusk", palette: "peck-deck", density: "compact" });
  });

  it("keeps a saved theme", () => {
    localStorage.setItem(KEY, JSON.stringify({ theme: "day", palette: "grove" }));
    expect(loadAppearance().palette).toBe("grove");
  });

  it("drops a theme id it does not know", () => {
    localStorage.setItem(KEY, JSON.stringify({ palette: "solarized" }));
    expect(loadAppearance().palette).toBe("peck-deck");
  });
});

describe("applyAppearance", () => {
  const root = document.documentElement;

  it("sets the theme's tokens for the chosen mode on <html>", () => {
    applyAppearance({ theme: "dusk", palette: "ocean", density: "comfortable" });
    const t = themeTokens("ocean", "dusk");
    expect(root.dataset.theme).toBe("dusk");
    expect(root.dataset.palette).toBe("ocean");
    expect(root.style.getPropertyValue("--bg")).toBe(t["--bg"]);
    expect(root.style.getPropertyValue("--pal-acc")).toBe(t["--pal-acc"]);
  });

  it("overwrites the last theme's tokens on a switch", () => {
    applyAppearance({ theme: "day", palette: "ember", density: "comfortable" });
    applyAppearance({ theme: "day", palette: "peck-deck", density: "comfortable" });
    expect(root.style.getPropertyValue("--bg")).toBe("#faf9f7");
  });

  it("points both theme-color tags at the active background", () => {
    applyAppearance({ theme: "day", palette: "grove", density: "comfortable" });
    const colours = [...document.querySelectorAll('meta[name="theme-color"]')]
      .map((m) => m.getAttribute("content"));
    expect(colours).toEqual([themeTokens("grove", "day")["--bg"], themeTokens("grove", "day")["--bg"]]);
  });
});
