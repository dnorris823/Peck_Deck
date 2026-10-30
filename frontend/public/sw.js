/* Peck Deck service worker.
 *
 * It does two jobs. It caches the app shell, so the installed app opens
 * without a network, and it receives web push (RFC 8291, decrypted by the
 * browser before it gets here) and turns it into a notification.
 *
 *   1. App shell        - network-first, cache fallback.
 *   2. Hashed assets    - cache-first. Filenames are content-addressed, so a
 *                         cached entry can never be stale.
 *   3. Icons and fonts  - cache-first, precached at install. Not hashed, so
 *                         a change to one needs a VERSION bump.
 *
 * API responses are never cached. A page that loads offline shows the shell
 * and the app says it is offline.
 *
 * Bump VERSION to invalidate every cache. Bump it too when a file in
 * public/fonts changes, because those URLs carry no content hash. Registration lives in
 * src/registerSW.js and only runs in production builds. A service worker in
 * front of the Vite dev server would serve stale modules and fight HMR.
 */
const VERSION = "v3";
const SHELL_CACHE = `peckdeck-shell-${VERSION}`;
const ASSET_CACHE = `peckdeck-assets-${VERSION}`;
const CURRENT_CACHES = [SHELL_CACHE, ASSET_CACHE];

// Enough to paint the app offline. Everything else arrives through the runtime
// caches on first online visit; listing hashed bundle names here is impossible
// without a build step reading the manifest.
const SHELL_URLS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon-180.png",
];

// The self-hosted font. Precached at install, not left to the runtime cache:
// on the very first visit the page fetches its fonts before this worker
// controls it, so a runtime cache would miss them and the first offline
// launch would fall back to the system face. Keep in step with the
// @font-face rules in src/styles.css.
const FONT_URLS = [
  "/fonts/plus-jakarta-sans-latin-wght-normal.woff2",
  "/fonts/plus-jakarta-sans-latin-wght-italic.woff2",
  "/fonts/plus-jakarta-sans-latin-ext-wght-normal.woff2",
  "/fonts/plus-jakarta-sans-latin-ext-wght-italic.woff2",
];

self.addEventListener("install", (event) => {
  // addAll is atomic: one 404 would fail the whole install and leave the
  // previous worker in place, so each URL is added on its own.
  const precache = (cacheName, urls) =>
    caches.open(cacheName).then((cache) =>
      Promise.all(urls.map((url) => cache.add(new Request(url, { cache: "reload" })).catch(() => {})))
    );
  event.waitUntil(Promise.all([precache(SHELL_CACHE, SHELL_URLS), precache(ASSET_CACHE, FONT_URLS)]));
  // No skipWaiting: a new worker takes over on the next visit instead of
  // swapping caches out from under a page that is still running.
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("peckdeck-") && !CURRENT_CACHES.includes(k))
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  // Lets the page opt into an immediate update ("Reload to update").
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // never cache a write

  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, SHELL_CACHE, "/index.html"));
    return;
  }

  if (url.origin !== self.location.origin) return; // other origins — leave alone

  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/fonts/")
  ) {
    event.respondWith(cacheFirst(request, ASSET_CACHE));
  }
});

/** Cache-first — for content-addressed files that cannot go stale. */
async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (isCacheable(response)) cache.put(request, response.clone());
  return response;
}

/**
 * Network-first for navigations: fresh when online, the cached shell when not.
 * Any in-scope URL falls back to index.html, since the app routes client-side.
 */
async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (isCacheable(response)) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = (await cache.match(request)) || (await cache.match(fallbackUrl));
    if (hit) return hit;
    throw err; // nothing sensible to render
  }
}

function isCacheable(response) {
  // Opaque (cross-origin no-cors) responses can't be inspected and cache.put
  // rejects them; a 401 must never be stored or it would outlive the session.
  return response && response.status === 200 && response.type !== "opaque";
}

// ── Web push ────────────────────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  // A push that shows nothing is treated as abuse by browsers (and can cost the
  // app its permission), so every branch ends in showNotification.
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
  }

  const title = payload.title || "Peck Deck";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "A bird visited your feeder.",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      // Collapses a backlog of alerts from one feeder into the latest.
      tag: payload.tag || "peckdeck",
      renotify: true,
      data: payload.data || {},
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin).href;

  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      // Prefer an open tab — focusing beats opening a second copy of the app.
      for (const client of clientList) {
        if (client.url.startsWith(self.location.origin) && "focus" in client) {
          await client.focus();
          if ("navigate" in client && client.url !== target) await client.navigate(target);
          return;
        }
      }
      await self.clients.openWindow(target);
    })()
  );
});
