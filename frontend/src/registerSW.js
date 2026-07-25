// Service worker registration — FLEDGE Phase 7.
//
// Production only. A service worker in front of the Vite dev server serves stale
// modules and fights HMR, and the dev proxy means /api responses would be cached
// against a URL shape that doesn't exist in a real deployment. To exercise it
// locally: `npm run build && npm run preview`.

const SW_URL = "/sw.js";

export function isSupported() {
  return typeof navigator !== "undefined" && "serviceWorker" in navigator;
}

/**
 * Register the worker and return the registration (or null when it can't or
 * shouldn't run). Never throws: an unavailable service worker degrades the app
 * to a plain online-only page, which is not worth an error screen.
 */
export async function registerServiceWorker({ force = false } = {}) {
  if (!isSupported()) return null;
  if (!force && !import.meta.env.PROD) return null;

  try {
    const registration = await navigator.serviceWorker.register(SW_URL, {
      scope: "/",
      // Always revalidate sw.js itself, so a deploy is picked up even if an
      // intermediary decided the old worker was cacheable.
      updateViaCache: "none",
    });
    // Check once on load rather than relying on the browser's own 24h cadence.
    registration.update?.().catch(() => {});
    return registration;
  } catch (err) {
    console.warn("[peckdeck] service worker registration failed:", err);
    return null;
  }
}
