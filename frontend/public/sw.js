/* Offline shell for Lexi.
 *
 * ponytail: a cache-first shell for static assets and a network-first pass for
 * pages, in ~30 lines - no Workbox. API responses are deliberately NOT cached:
 * a stale band score or review queue is worse than an honest "you are offline".
 */
const CACHE = "lexi-shell-v1";
const SHELL = ["/", "/dashboard", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;   // never touch API or media hosts

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok && request.destination !== "document") {
          const copy = response.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match("/dashboard")))
  );
});
