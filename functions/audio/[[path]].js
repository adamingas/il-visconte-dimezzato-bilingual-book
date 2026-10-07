const AUDIO_KEY = 'il_visconte_dimezzato_EP71iMmmc0Q.webm';
const AUDIO_PATH = `/audio/${AUDIO_KEY}`;

function responseHeaders(object) {
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('Accept-Ranges', 'bytes');
  headers.set('Cache-Control', headers.get('Cache-Control') || 'public, max-age=3600');
  headers.set('ETag', object.httpEtag);
  headers.set('X-Content-Type-Options', 'nosniff');
  return headers;
}

function notAllowed() {
  return new Response('Method Not Allowed', {
    status: 405,
    headers: { Allow: 'GET, HEAD' },
  });
}

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  if (url.pathname !== AUDIO_PATH) return new Response('Not Found', { status: 404 });
  if (request.method !== 'GET' && request.method !== 'HEAD') return notAllowed();

  if (request.method === 'HEAD') {
    const object = await env.AUDIO_BUCKET.head(AUDIO_KEY);
    if (object === null) return new Response('Not Found', { status: 404 });

    const headers = responseHeaders(object);
    headers.set('Content-Length', String(object.size));
    return new Response(null, { status: 200, headers });
  }

  // Cloudflare may strip Range before invoking a cacheable Function and perform
  // the slicing at the edge. Only emit 206 when this Function actually received
  // a Range header; a full R2 read also exposes range metadata.
  const requestedRange = request.headers.has('Range');
  let object;
  try {
    object = await env.AUDIO_BUCKET.get(
      AUDIO_KEY,
      requestedRange
        ? { onlyIf: request.headers, range: request.headers }
        : { onlyIf: request.headers },
    );
  } catch (error) {
    if (request.headers.has('Range')) {
      const metadata = await env.AUDIO_BUCKET.head(AUDIO_KEY);
      const headers = new Headers({ 'Accept-Ranges': 'bytes' });
      if (metadata) headers.set('Content-Range', `bytes */${metadata.size}`);
      return new Response(null, { status: 416, headers });
    }
    throw error;
  }

  if (object === null) return new Response('Not Found', { status: 404 });

  const headers = responseHeaders(object);
  if (!('body' in object)) return new Response(null, { status: 412, headers });

  let status = 200;
  if (
    requestedRange
    && object.range
    && Number.isFinite(object.range.offset)
    && Number.isFinite(object.range.length)
  ) {
    const start = object.range.offset;
    const end = start + object.range.length - 1;
    headers.set('Content-Range', `bytes ${start}-${end}/${object.size}`);
    headers.set('Content-Length', String(object.range.length));
    status = 206;
  } else {
    headers.set('Content-Length', String(object.size));
  }

  return new Response(object.body, { status, headers });
}
