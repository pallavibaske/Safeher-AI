/* SafeHer AI service worker: offline fallback + faster static files */
const V = 'safeher-v1';
const PRE = ['/offline', '/static/style.css', '/static/app.js', '/static/icons/icon-192.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(PRE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin) return;
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).catch(() => caches.match('/offline')));
    return;
  }
  if (u.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(r).then(hit => {
      const net = fetch(r).then(res => { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); return res; }).catch(() => hit);
      return hit || net;
    }));
  }
});
