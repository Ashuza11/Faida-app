/**
 * Faida Service Worker
 *
 * Cache strategies:
 *   - Static assets (CSS/JS/fonts/images): Cache-first
 *   - HTML pages: Network-first with TWO fallback layers:
 *       1. Server returned a redirect (e.g. DB is down → load_user returns None → login redirect)
 *          → Intercept the redirect, serve from cache instead
 *       2. Network completely unreachable (true offline)
 *          → Serve from cache, then offline.html
 *
 * This means the app works in both scenarios:
 *   a) Client truly offline (Render + phone disconnects): fetch() throws → cache ✓
 *   b) Local Docker + internet disconnected: server reachable but redirects → cache ✓
 */

const CACHE_VERSION = 'faida-v3';
const OFFLINE_URL   = '/static/offline.html';

// Static assets pre-cached on install (no auth needed)
const PRECACHE_ASSETS = [
  '/static/offline.html',
  '/static/assets/css/argon.css?v=1.2.0',
  '/static/assets/js/argon.js?v=1.2.0',
  '/static/assets/vendor/nucleo/css/nucleo.css',
  '/static/assets/vendor/@fortawesome/fontawesome-free/css/all.min.css',
  '/static/js/faida-offline.js',
];

// ── Install: pre-cache static assets ─────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then((cache) => cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[SW] Some assets failed to pre-cache (CDN offline?):', err);
      }))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ───────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: routing ────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. Skip non-GET (POST form submits go through normally; faida-offline.js intercepts them)
  if (request.method !== 'GET') return;

  // 2. Cross-origin requests (Google Fonts, CDN) — fail silently, never cache
  if (url.origin !== self.location.origin) {
    event.respondWith(
      fetch(request).catch(() => new Response('', { status: 408 }))
    );
    return;
  }

  // 3. API endpoints — always network, never cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // 4. Static assets — cache-first
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // 5. HTML pages — network-first with smart redirect + offline fallback
  event.respondWith(networkFirstWithFallback(request));
});

// ── Strategy: Cache-first ─────────────────────────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 408 });
  }
}

// ── Strategy: Network-first with redirect interception + offline fallback ─────
//
// KEY FIX: when the Flask server is reachable but the DB is down, load_user()
// returns None and @login_required issues a 302 redirect to /auth/login.
// fetch() follows it automatically, so response.redirected === true and
// response.url ends up at the login page.
//
// We intercept that case and serve the cached version of the originally-
// requested page instead, keeping the user "logged in" from their perspective.
//
// This handles both:
//   • True offline  (fetch throws NetworkError)   → Case C
//   • Server-side redirect due to DB being down   → Case A
async function networkFirstWithFallback(request) {
  try {
    const response = await fetch(request);

    // ── Case A: Server redirected to login (DB down / session lost) ───────
    if (response.redirected && response.url.includes('/auth/login')) {
      const cached = await caches.match(request);
      if (cached) {
        // Serve the cached version — user stays on their page
        return cached;
      }
      // No cached version yet; pass the login redirect through
      return response;
    }

    // ── Case B: Valid response ────────────────────────────────────────────
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;

  } catch {
    // ── Case C: True offline (fetch threw — Render unreachable, phone offline)
    const cached = await caches.match(request);
    if (cached) return cached;

    // No cache at all → offline fallback page
    if (request.mode === 'navigate') {
      const offlinePage = await caches.match(OFFLINE_URL);
      return offlinePage || new Response('<h1>Hors ligne</h1>', {
        status: 503,
        headers: { 'Content-Type': 'text/html' },
      });
    }
    return new Response('Offline', { status: 503 });
  }
}

// ── Background Sync ───────────────────────────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'faida-sync') {
    event.waitUntil(syncPendingOps());
  }
});

async function syncPendingOps() {
  const db  = await openDB();
  const ops = await getAllPending(db);

  for (const op of ops) {
    try {
      const response = await fetch(endpointFor(op.type), {
        method:      'POST',
        headers:     { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body:        JSON.stringify(op.data),
        credentials: 'same-origin',
      });
      if (response.ok || response.status === 409) {
        await markSynced(db, op.id);
      }
    } catch {
      // Network still unavailable — leave as pending, retry next sync
    }
  }
  db.close();
}

function endpointFor(type) {
  const map = {
    sale:           '/api/v1/sales',
    stock_purchase: '/api/v1/stock-purchases',
    cash_outflow:   '/api/v1/cash-outflows',
  };
  return map[type] || '/api/v1/health';
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function isStaticAsset(pathname) {
  return (
    pathname.startsWith('/static/') ||
    pathname.endsWith('.css')   ||
    pathname.endsWith('.js')    ||
    pathname.endsWith('.woff2') ||
    pathname.endsWith('.woff')  ||
    pathname.endsWith('.png')   ||
    pathname.endsWith('.jpg')   ||
    pathname.endsWith('.ico')   ||
    pathname.endsWith('.svg')
  );
}

// ── IndexedDB helpers (SW context) ───────────────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('faida_offline', 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('faida_queue')) {
        const store = db.createObjectStore('faida_queue', { keyPath: 'id', autoIncrement: true });
        store.createIndex('status',   'status',   { unique: false });
        store.createIndex('local_id', 'local_id', { unique: true  });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror   = (e) => reject(e.target.error);
  });
}

function getAllPending(db) {
  return new Promise((resolve, reject) => {
    const tx    = db.transaction('faida_queue', 'readonly');
    const index = tx.objectStore('faida_queue').index('status');
    const req   = index.getAll('pending');
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror   = (e) => reject(e.target.error);
  });
}

function markSynced(db, id) {
  return new Promise((resolve, reject) => {
    const tx    = db.transaction('faida_queue', 'readwrite');
    const store = tx.objectStore('faida_queue');
    const req   = store.get(id);
    req.onsuccess = (e) => {
      const record = e.target.result;
      if (record) { record.status = 'synced'; store.put(record); }
      resolve();
    };
    req.onerror = (e) => reject(e.target.error);
  });
}
