/**
 * QuizAssist PWA Service Worker
 * Version: 1.0.1
 */

const CACHE_NAME = 'quizassist-v1.0.1';

const PRECACHE_ASSETS = [
    '/offline',
    '/static/css/main.css?v=2.2',
    '/static/js/main.js',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/icons/favicon.png',
    '/static/icons/icon.svg',
    '/manifest.json'
];

// Install: Pre-cache core app shell assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS).catch((err) => {
                console.warn('[SW] Some precache assets failed:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// Activate: Clean up old cache versions and claim clients
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch: Smart routing strategy
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // 1. Never intercept non-GET requests (POST, DELETE, PUT)
    if (request.method !== 'GET') {
        return;
    }

    // 2. Bypass caching completely for API routes, SSE streams, auth flows
    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/login') ||
        url.pathname.startsWith('/logout')
    ) {
        return; // Normal network request
    }

    // 3. Navigation requests (HTML pages): Network-First with Offline fallback
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    // Cache successful navigation responses for fast reloads
                    if (response && response.status === 200) {
                        const copy = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
                    }
                    return response;
                })
                .catch(async () => {
                    const cachedResponse = await caches.match(request);
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // If no cached version exists, show the offline page
                    const offlinePage = await caches.match('/offline');
                    return offlinePage || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
                })
        );
        return;
    }

    // 4. Static assets (CSS, JS, Fonts, Icons): Stale-While-Revalidate
    if (
        url.pathname.startsWith('/static/') ||
        url.hostname.includes('fonts.googleapis.com') ||
        url.hostname.includes('fonts.gstatic.com')
    ) {
        event.respondWith(
            caches.match(request).then((cachedResponse) => {
                const fetchPromise = fetch(request)
                    .then((networkResponse) => {
                        if (networkResponse && networkResponse.status === 200) {
                            const copy = networkResponse.clone();
                            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
                        }
                        return networkResponse;
                    })
                    .catch(() => cachedResponse);

                return cachedResponse || fetchPromise;
            })
        );
    }
});
