// Service worker: makes the buildless SPA installable and offline-tolerant.
//
// Strategy is deliberately conservative for a hand-maintained app:
//   - The static shell (index.html, CSS, every JS module, icons) is precached on
//     install and served network-first with a cache fallback -- so it always
//     runs the latest code when online, and still loads when offline.
//   - /api/* is never touched: those requests pass straight to the network, so
//     auth, CSRF and freshness are unchanged, and nothing attempts offline
//     writes (the guarded-UPDATE model has no offline reconciliation).
//
// Buildless means the precache list is maintained by hand -- when a NEW js module
// is added, append it here (a missing one just falls back to network) and bump
// CACHE so old caches are purged.

const CACHE = "nlm-shell-v1";

const SHELL = [
  "/",
  "/index.html",
  "/css/styles.css",
  "/favicon.svg",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/js/analytics.js", "/js/app.js", "/js/auth.js", "/js/catalog.js",
  "/js/controlled.js", "/js/counts.js", "/js/equipment.js", "/js/funds.js",
  "/js/game.js", "/js/glassware.js", "/js/help.js", "/js/history.js",
  "/js/inventory.js", "/js/it.js", "/js/kits.js", "/js/labels.js",
  "/js/maintenance.js", "/js/map.js", "/js/people.js", "/js/preparations.js",
  "/js/purchasing.js", "/js/reports.js", "/js/safety.js", "/js/scanner.js",
  "/js/settings.js", "/js/sql.js", "/js/tickets.js", "/js/usage.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // addAll is atomic; ignore individual misses so one 404 never bricks install.
      .then((cache) => Promise.allSettled(SHELL.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                       // never intercept writes
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;        // same-origin only
  if (url.pathname.startsWith("/api/")) return;           // API always hits network

  // Network-first: always prefer fresh code; fall back to the cached shell
  // (or the app root) when offline.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
  );
});
