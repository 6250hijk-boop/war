const CACHE_NAME = 'war-survival-chatbot-offline-v3';
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
      Promise.all(keys.filter(k => k.startsWith('war-survival-chatbot-offline-') && k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const reqUrl = event.request.url.split('#')[0];

  // PDF 파일은 용량이 크므로 캐시 우선(Cache-First)으로 오프라인 열람 속도 확보
  if (reqUrl.toLowerCase().endsWith('.pdf')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async cache => {
        const cached = await cache.match(reqUrl);
        if (cached) return cached;
        try {
          const netRes = await fetch(event.request);
          if (netRes && netRes.status === 200) {
            cache.put(reqUrl, netRes.clone());
          }
          return netRes;
        } catch (_) {
          return Response.error();
        }
      })
    );
    return;
  }

  // HTML/JS/JSON 앱 파일은 온라인 시 항상 최신 버전 우선(Network-First), 오프라인 시 캐시 폴백
  event.respondWith(
    caches.open(CACHE_NAME).then(async cache => {
      try {
        const netRes = await fetch(event.request);
        if (netRes && (netRes.status === 200 || netRes.type === 'opaque')) {
          cache.put(reqUrl, netRes.clone());
        }
        return netRes;
      } catch (_) {
        const cached = await cache.match(reqUrl);
        return cached || (await caches.match('./index.html'));
      }
    })
  );
});
