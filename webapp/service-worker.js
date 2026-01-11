const CACHE_NAME = 'aurora-hifi-v41'; // Updated cache
const ASSETS = [
    './', './index.html', './style.css',
    './js/main.js', './js/api.js', './js/player.js',
    './js/store.js', './js/ui.js', './js/genres.js', './js/visualizer.js',
    './js/haptics.js', './js/ai.js',
    './favicon.svg'
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
    
    const url = new URL(e.request.url);
    
    // Исключаем внешние скрипты (Telegram) и API
    if (url.hostname.includes('telegram') || url.pathname.includes('/api/') || url.pathname.includes('/audio/')) {
        e.respondWith(fetch(e.request));
        return;
    }
    
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
