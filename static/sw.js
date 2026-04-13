/* UniPortal Service Worker v5 */
const CACHE = 'uniportal-v5';
const ASSETS = ['/', '/manifest.json'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ASSETS))
      .catch(() => {})
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/api/') || e.request.url.includes('/uploads/')) return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

/* ── PUSH NOTIFICATION HANDLER ── */
self.addEventListener('push', e => {
  let data = {
    title: 'UniPortal 🧬',
    body: 'إشعار جديد',
    url: '/',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/badge-72.png'
  };
  try {
    const parsed = e.data ? JSON.parse(e.data.text()) : {};
    data = { ...data, ...parsed };
  } catch(err) {}

  const options = {
    body: data.body,
    icon: data.icon || '/static/icons/icon-192.png',
    badge: data.badge || '/static/icons/badge-72.png',
    dir: 'rtl',
    lang: 'ar',
    vibrate: [200, 100, 200],
    tag: data.tag || 'uniportal-notif',
    renotify: true,
    data: { url: data.url || '/' },
    actions: [
      { action: 'open', title: '📖 فتح' },
      { action: 'dismiss', title: '✕ إغلاق' }
    ]
  };

  e.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

/* ── NOTIFICATION CLICK ── */
self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;

  const url = e.notification.data?.url || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(list => {
        for (const client of list) {
          if (client.url.includes(self.location.origin)) {
            client.focus();
            client.navigate(url);
            return;
          }
        }
        return clients.openWindow(url);
      })
  );
});

/* ── BACKGROUND SYNC: poll for notifications ── */
self.addEventListener('sync', e => {
  if (e.tag === 'poll-notifs') {
    e.waitUntil(pollAndNotify());
  }
});

/* ── PERIODIC SYNC (if supported) ── */
self.addEventListener('periodicsync', e => {
  if (e.tag === 'poll-notifs') {
    e.waitUntil(pollAndNotify());
  }
});

async function pollAndNotify() {
  try {
    const clients_list = await clients.matchAll({ includeUncontrolled: true });
    if (clients_list.length > 0) return; // App is open, don't double notify
  } catch(e) {}
}
