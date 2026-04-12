const CACHE = 'uniportal-v6-20260412';
const CORE_ASSETS = [
  '/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/badge-72.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE_ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/api/')) return;
  const url = new URL(e.request.url);
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          const clone = resp.clone();
          caches.open(CACHE).then(cache => cache.put('/', clone)).catch(() => {});
          return resp;
        })
        .catch(() => caches.match('/') || caches.match(e.request))
    );
    return;
  }
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          const clone = resp.clone();
          if (!url.pathname.startsWith('/uploads/')) {
            caches.open(CACHE).then(cache => cache.put(e.request, clone)).catch(() => {});
          }
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
  }
});

self.addEventListener('push', e => {
  let data = { title: 'UniPortal 🧬', body: 'إشعار جديد', url: '/' };
  try { data = { ...data, ...JSON.parse(e.data.text()) }; } catch {}
  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/badge-72.png',
      dir: 'rtl', lang: 'ar',
      vibrate: [200, 100, 200],
      data: { url: data.url },
      actions: [
        { action: 'open', title: 'فتح' },
        { action: 'close', title: 'إغلاق' }
      ]
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'close') return;
  const url = e.notification.data?.url || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (c.url.includes(self.location.origin)) {
          c.focus(); c.navigate(url); return;
        }
      }
      clients.openWindow(url);
    })
  );
});
