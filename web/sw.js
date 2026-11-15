// Network first; fall back to the cached shell so the app opens offline with its last view.
const SHELL = 'finn-shell-v1';
self.addEventListener('install', e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(['/', 'styles.css', 'app.js', 'icon.svg']))); self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET' || new URL(e.request.url).pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request)));
});
self.addEventListener('notificationclick', e => { e.notification.close(); e.waitUntil(self.clients.openWindow('/')); });
