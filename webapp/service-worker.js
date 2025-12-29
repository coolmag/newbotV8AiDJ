const CACHE_NAME = 'aurora-player-v8.2';
const ASSETS = [
    './', './index.html', './style.css',
    './js/main.js', './js/api.js', './js/player.js',
    './js/store.js', './js/ui.js', './js/genres.js', 
    './js/visualizer.js', './js/haptics.js', './js/ai.js'
];

self.addEventListener('install', e => {
    self.skipWaiting(); 
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
});

self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(k => Promise.all(
        k.map(n => n !== CACHE_NAME ? caches.delete(n) : null)
    )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    if (e.request.url.includes('/api/') || e.request.url.includes('/audio/')) {
        e.respondWith(fetch(e.request));
        return;
    }
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});