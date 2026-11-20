const CACHE_NAME = 'war-survival-chatbot-offline-v2';
const CORE_ASSETS = [
  './',
  './index.html',
  './knowledge_base.js',
  './manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(k => (k !== CACHE_NAME ? caches.delete(k) : null)))
    )
  );
  self.clients.claim();
});

// PDF 파일을 포함한 모든 요청을 캐시 우선 + 네트워크 폴백으로 처리하고, 한 번 열람한 PDF는 영구 오프라인 캐싱
self.addEventListener('fetch', event => {
  const reqUrl = event.request.url.split('#')[0];
  event.respondWith(
    caches.open(CACHE_NAME).then(async cache => {
      const cached = await cache.match(reqUrl);
      if (cached) return cached;
      try {
        const netRes = await fetch(event.request);
        if (netRes && netRes.status === 200 && event.request.method === 'GET') {
          cache.put(reqUrl, netRes.clone());
        }
        return netRes;
      } catch (_) {
        return caches.match('./index.html');
      }
    })
  );
});
