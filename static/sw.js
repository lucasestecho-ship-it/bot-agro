const CACHE_NAME = "capataz-campo-v11";
const ASSETS = [
  "/campo",
  "/static/campo.css",
  "/static/campo.js",
  "/static/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request);
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/campo";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const existing = windows.find((client) => client.url.includes("/campo"));
      if (existing) return existing.focus();
      return clients.openWindow(targetUrl);
    })
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data?.json() || {};
  } catch {
    payload = { body: event.data?.text() || "Tenés pendientes para revisar" };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "Capataz Campo", {
      body: payload.body || "Tenés pendientes para revisar",
      icon: "/static/logo.png",
      badge: "/static/logo.png",
      tag: payload.tag || "capataz-daily",
      data: { url: payload.url || "/campo" },
    })
  );
});
