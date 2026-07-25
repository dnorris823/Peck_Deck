/**
 * The PWA's static assets are plain files no bundler validates, so a typo in the
 * manifest or a renamed icon would only surface as a phone silently refusing to
 * install the app. These read the real files off disk.
 */
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const PUBLIC = join(process.cwd(), "public");
const manifest = JSON.parse(
  readFileSync(join(PUBLIC, "manifest.webmanifest"), "utf8")
);
const indexHtml = readFileSync(join(process.cwd(), "index.html"), "utf8");
const sw = readFileSync(join(PUBLIC, "sw.js"), "utf8");

describe("web app manifest", () => {
  it("declares what a browser needs to offer installation", () => {
    expect(manifest.name).toMatch(/Peck Deck/);
    expect(manifest.short_name.length).toBeLessThanOrEqual(12); // home-screen label
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("ships the icon sizes install prompts require", () => {
    const sizes = manifest.icons.map((i) => i.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
  });

  it("ships a maskable icon so Android doesn't letterbox the mark", () => {
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
  });

  it("references only icons that exist", () => {
    for (const icon of manifest.icons) {
      expect(existsSync(join(PUBLIC, icon.src)), `missing ${icon.src}`).toBe(true);
    }
  });

  it("uses brand tokens for the install splash", () => {
    // Must match --paper in styles.css, or the splash flashes a foreign color.
    expect(manifest.background_color).toBe("#f3ede0");
    expect(manifest.theme_color).toBe("#f3ede0");
  });

  it("points every shortcut at a screen the app can actually route to", () => {
    // App.jsx maps ?screen=<id> onto the nav ids.
    const known = ["dashboard", "sightings", "species", "devices", "users", "settings"];
    for (const shortcut of manifest.shortcuts ?? []) {
      const screen = new URL(shortcut.url, "https://example.com").searchParams.get("screen");
      expect(known, `unknown screen in ${shortcut.url}`).toContain(screen);
    }
  });
});

describe("index.html", () => {
  it("links the manifest and the iOS home-screen icon", () => {
    expect(indexHtml).toMatch(/rel="manifest" href="\/manifest\.webmanifest"/);
    expect(indexHtml).toMatch(/rel="apple-touch-icon"/);
  });

  it("declares a theme color for both schemes", () => {
    expect(indexHtml).toMatch(/theme-color".*prefers-color-scheme: light/);
    expect(indexHtml).toMatch(/theme-color".*prefers-color-scheme: dark/);
  });

  it("opts into the notch area, which the safe-area CSS then pads around", () => {
    expect(indexHtml).toMatch(/viewport-fit=cover/);
  });

  it("references icons that exist", () => {
    for (const [, href] of indexHtml.matchAll(/href="(\/icons\/[^"]+)"/g)) {
      expect(existsSync(join(PUBLIC, href)), `missing ${href}`).toBe(true);
    }
  });
});

describe("service worker", () => {
  it("handles the push and notificationclick events", () => {
    expect(sw).toMatch(/addEventListener\("push"/);
    expect(sw).toMatch(/addEventListener\("notificationclick"/);
  });

  it("always shows a notification for a push", () => {
    // A silent push is treated as abuse and can cost the app its permission.
    expect(sw).toMatch(/showNotification/);
  });

  it("precaches the shell entry point", () => {
    expect(sw).toMatch(/"\/index\.html"/);
  });

  it("refuses to cache anything but GET", () => {
    expect(sw).toMatch(/request\.method !== "GET"/);
  });

  it("only stores 200s, so a 401 can never outlive the session", () => {
    expect(sw).toMatch(/response\.status === 200/);
  });
});
