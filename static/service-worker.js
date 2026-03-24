
const CACHE_NAME = 'farmpulse-v4';
const ASSETS = [
  '/', '/weather', '/plant', '/soil', '/chat', '/report', '/irrigation', '/diseases', '/recommendations', '/market',
  '/static/style.css', '/static/app.js', '/manifest.json', '/static/img/logo.png', '/static/img/logo-192.png', '/static/img/logo-512.png', '/service-worker.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match('/')))
  );
});
