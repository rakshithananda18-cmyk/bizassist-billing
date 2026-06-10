/**
 * BizAssist Service Worker
 * Strategy: cache-first for static assets, network-first for API calls.
 * Provides offline shell so the app loads even with no connectivity.
 */

const CACHE_NAME = "bizassist-v1";

// Static assets to pre-cache on install (app shell)
const PRECACHE_URLS = [
  "/",
  "/index.html",
];

// Never cache these — always go to network
const NETWORK_ONLY = [
  "/api/",
  "/login",
  "/signup",
  "/ask",
  "/upload",
];

// ── Install: pre-cache the app shell ────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ──────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch: cache-first for assets, network-first for API ────────────────────
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Always go to network for API routes
  if (NETWORK_ONLY.some((path) => url.pathname.startsWith(path))) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Cache-first for everything else (JS, CSS, fonts, icons)
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;

      return fetch(event.request)
        .then((response) => {
          // Only cache successful GET responses
          if (
            event.request.method === "GET" &&
            response.status === 200 &&
            response.type !== "opaque"
          ) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => {
          // Offline fallback: serve cached index.html for navigation requests
          if (event.request.mode === "navigate") {
            return caches.match("/index.html");
          }
        });
    })
  );
});
