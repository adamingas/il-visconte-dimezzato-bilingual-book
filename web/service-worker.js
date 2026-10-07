const SHELL_CACHE = 'viscount-shell-v9';
const AUDIO_CACHE = 'viscount-audio-v2';
const AUDIO_URL = new URL('./audio/il_visconte_dimezzato_EP71iMmmc0Q.webm?v=2', self.location).href;
const SHELL = [
  './',
  './viscount-audio-alignment.json',
  './manifest.webmanifest',
  './app-icon.svg',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(names => Promise.all(
      names
        .filter(name => (
          (name.startsWith('viscount-shell-') && name !== SHELL_CACHE)
          || (name.startsWith('viscount-audio-') && name !== AUDIO_CACHE)
        ))
        .map(name => caches.delete(name)),
    )),
  );
  self.clients.claim();
});

async function cachedAudio(request) {
  const cached = await (await caches.open(AUDIO_CACHE)).match(AUDIO_URL);
  if (!cached) return fetch(request);

  const range = request.headers.get('range');
  if (!range) return cached;

  const match = /^bytes=(\d+)-(\d*)$/.exec(range);
  if (!match) return new Response(null, { status: 416 });
  const blob = await cached.blob();
  const start = Number(match[1]);
  const end = match[2] ? Math.min(Number(match[2]), blob.size - 1) : blob.size - 1;
  if (start > end || start >= blob.size) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${blob.size}` },
    });
  }
  const slice = blob.slice(start, end + 1, cached.headers.get('Content-Type') || 'audio/webm');
  return new Response(slice, {
    status: 206,
    headers: {
      'Accept-Ranges': 'bytes',
      'Content-Length': String(slice.size),
      'Content-Range': `bytes ${start}-${end}/${blob.size}`,
      'Content-Type': slice.type,
    },
  });
}

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (url.href === AUDIO_URL) {
    event.respondWith(cachedAudio(event.request));
    return;
  }

  if (event.request.mode === 'navigate') {
    const networkResponse = fetch(event.request);
    // Keep the cache write alive after the network response is handed to the
    // page. Without waitUntil(), browsers may terminate this update early.
    event.waitUntil(
      networkResponse
        .then(response => caches.open(SHELL_CACHE).then(
          cache => cache.put(event.request, response.clone()),
        ))
        .catch(() => undefined),
    );
    event.respondWith(
      networkResponse.catch(() => caches.match(event.request).then(
        cached => cached || caches.match('./'),
      )),
    );
    return;
  }

  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
