import assert from 'node:assert/strict';
import test from 'node:test';

import { onRequest } from '../functions/audio/[[path]].js';


const AUDIO_PATH = '/audio/il_visconte_dimezzato_EP71iMmmc0Q.webm';
const AUDIO_BYTES = new TextEncoder().encode('0123456789');

function r2Object(bytes = AUDIO_BYTES, range = undefined) {
  return {
    body: bytes,
    size: AUDIO_BYTES.byteLength,
    range,
    httpEtag: '"audio-etag"',
    httpMetadata: { contentType: 'audio/webm' },
    writeHttpMetadata(headers) {
      headers.set('Content-Type', this.httpMetadata.contentType);
    },
  };
}

function context(method = 'GET', headers = {}) {
  return {
    request: new Request(`https://viscount.spanashis.com${AUDIO_PATH}`, { method, headers }),
    env: {
      AUDIO_BUCKET: {
        async head() {
          const { body: _body, ...metadata } = r2Object();
          return metadata;
        },
        async get(_key, options) {
          // R2 can expose a full-object range even for a non-range read. The
          // Function must still return 200 unless the client requested a range.
          if (!options.range) {
            return r2Object(AUDIO_BYTES, { offset: 0, length: AUDIO_BYTES.byteLength });
          }
          return r2Object(AUDIO_BYTES.slice(2, 6), { offset: 2, length: 4 });
        },
      },
    },
  };
}

test('streams the complete audiobook with media metadata', async () => {
  const response = await onRequest(context());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'audio/webm');
  assert.equal(response.headers.get('Accept-Ranges'), 'bytes');
  assert.equal(response.headers.get('Content-Length'), '10');
  assert.equal(await response.text(), '0123456789');
});

test('does not pass range options to R2 for a complete download', async () => {
  let receivedOptions;
  const ctx = context();
  const originalGet = ctx.env.AUDIO_BUCKET.get;
  ctx.env.AUDIO_BUCKET.get = async (key, options) => {
    receivedOptions = options;
    return originalGet(key, options);
  };

  const response = await onRequest(ctx);
  assert.equal(response.status, 200);
  assert.equal(receivedOptions.range, undefined);
});

test('returns a correct partial-content response for browser seeking', async () => {
  const response = await onRequest(context('GET', { Range: 'bytes=2-5' }));
  assert.equal(response.status, 206);
  assert.equal(response.headers.get('Content-Range'), 'bytes 2-5/10');
  assert.equal(response.headers.get('Content-Length'), '4');
  assert.equal(await response.text(), '2345');
});

test('supports metadata-only HEAD requests', async () => {
  const response = await onRequest(context('HEAD'));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Length'), '10');
  assert.equal(await response.text(), '');
});

test('does not expose arbitrary R2 objects', async () => {
  const ctx = context();
  ctx.request = new Request('https://viscount.spanashis.com/audio/private.epub');
  const response = await onRequest(ctx);
  assert.equal(response.status, 404);
});
