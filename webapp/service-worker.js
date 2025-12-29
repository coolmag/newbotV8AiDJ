const CACHE_NAME = 'aurora-player-v28';
const ASSETS = [
    './', './index.html', './style.css',
    './js/main.js', './js/api.js', './js/player.js',
    './js/store.js', './js/ui.js', './js/genres.js', './js/visualizer.js',
    './js/haptics.js', './js/ai.js', // Не забудьте новые файлы
    './favicon.svg'
];

self.addEventListener('install', e => {
    self.skipWaiting(); 
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
});

self.addEventListener('activate', e => {
    // Удаляем старые кэши (v11, v12 и т.д.)
    e.waitUntil(caches.keys().then(k => Promise.all(
        k.map(n => n !== CACHE_NAME ? caches.delete(n) : null)
    )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    // API и аудио всегда берем из сети
    if (e.request.url.includes('/api/') || e.request.url.includes('/audio/')) {
        e.respondWith(fetch(e.request));
        return;
    }
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});