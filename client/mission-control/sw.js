const CACHE = "tinyrooms-entry-v2";
const BASE = new URL("./", self.registration.scope);
const SHELL = BASE.href;
const PRECACHE = [
  SHELL,
  new URL("mission-control/css/entry.css", BASE).href,
  new URL("mission-control/js/entry.js", BASE).href,
  new URL("mission-control/js/entry-scene.js", BASE).href,
  new URL("mission-control/js/entry-showcase-layout.js", BASE).href,
  new URL("manifest.webmanifest", BASE).href,
  new URL("icons/icon-192.png", BASE).href,
  new URL("icons/icon-512.png", BASE).href,
  new URL("icons/icon-maskable-512.png", BASE).href,
  new URL("icons/apple-touch-icon-180.png", BASE).href,
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname !== BASE.pathname) return;
  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response.ok) {
        const cache = await caches.open(CACHE);
        await cache.put(SHELL, response.clone());
      }
      return response;
    } catch {
      const cached = await caches.match(SHELL);
      return cached || new Response("Tinyrooms is offline. Reconnect and try again.", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
  })());
});
