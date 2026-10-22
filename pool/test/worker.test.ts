import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../workers/api/index.js';

const ORIGIN = 'https://example.invalid/data';

function req(path: string, init?: RequestInit): Request {
  return new Request(`https://api.test${path}`, init);
}

const env = { ORIGIN } as { ORIGIN: string };

const originalFetch = globalThis.fetch;

test('worker: OPTIONS is preflighted', async () => {
  const res = await worker.fetch(req('/v1/stats', { method: 'OPTIONS' }), env);
  assert.equal(res.status, 204);
  assert.equal(res.headers.get('access-control-allow-origin'), '*');
});

test('worker: index lists the endpoints', async () => {
  const res = await worker.fetch(req('/'), env);
  assert.equal(res.status, 200);
  const body = (await res.json()) as { endpoints: string[] };
  assert.ok(body.endpoints.includes('/v1/stats'));
  assert.equal(res.headers.get('access-control-allow-origin'), '*');
});

test('worker: unknown path is a 404 json error', async () => {
  const res = await worker.fetch(req('/v1/nope'), env);
  assert.equal(res.status, 404);
  assert.equal(res.headers.get('content-type'), 'application/json; charset=utf-8');
});

test('worker: only GET and OPTIONS are served', async () => {
  for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
    const res = await worker.fetch(req('/v1/stats', { method }), env);
    assert.equal(res.status, 405, `${method} must be 405`);
  }
});

test('worker: an unset ORIGIN is a clean 502, not a crash', async () => {
  const res = await worker.fetch(req('/v1/stats'), {});
  assert.equal(res.status, 502);
  const body = (await res.json()) as { error: string; hint?: string };
  assert.equal(body.error, 'ORIGIN binding missing');
  assert.match(body.hint!, /wrangler secret put ORIGIN/);
});

test('worker: /v1/ serves the index like /v1', async () => {
  const res = await worker.fetch(req('/v1/'), env);
  assert.equal(res.status, 200);
});

test('worker: history serves the time series, not meta.json', async () => {
  let seenUrl = '';
  globalThis.fetch = (async (url: unknown) => {
    seenUrl = String(url);
    return new Response(JSON.stringify([{ ts: 1, total: 10 }]), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof fetch;
  try {
    const res = await worker.fetch(req('/v1/history'), env);
    assert.equal(res.status, 200);
    assert.match(seenUrl, /history\.json$/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('worker: origin failure surfaces as 502', async () => {
  globalThis.fetch = (async () => {
    throw new Error('network down');
  }) as typeof fetch;
  try {
    const res = await worker.fetch(req('/v1/stats'), env);
    assert.equal(res.status, 502);
    const body = (await res.json()) as { error: string };
    assert.equal(body.error, 'origin fetch failed');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('worker: proxies json from origin with cache headers', async () => {
  globalThis.fetch = (async (url: unknown) => {
    assert.match(String(url), /\/data\/stats\.json$/);
    return new Response(JSON.stringify({ total: 2232 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof fetch;
  try {
    const res = await worker.fetch(req('/v1/stats'), env);
    assert.equal(res.status, 200);
    assert.equal(((await res.json()) as { total: number }).total, 2232);
    assert.match(res.headers.get('cache-control')!, /s-maxage=300/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('worker: text lists pass through as text/plain', async () => {
  globalThis.fetch = (async (url: unknown) => {
    assert.match(String(url), /\/data\/socks5\.txt$/);
    return new Response('socks5://1.2.3.4:1080\n', { status: 200 });
  }) as typeof fetch;
  try {
    const res = await worker.fetch(req('/v1/list/socks5'), env);
    assert.equal(res.status, 200);
    assert.match(res.headers.get('content-type')!, /text\/plain/);
    assert.match(await res.text(), /socks5:\/\/1\.2\.3\.4:1080/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('worker: country shard path is uppercased', async () => {
  globalThis.fetch = (async (url: unknown) => {
    assert.match(String(url), /\/data\/country\/US\.txt$/);
    return new Response('socks5://1.2.3.4:1080\n', { status: 200 });
  }) as typeof fetch;
  try {
    const res = await worker.fetch(req('/v1/country/us'), env);
    assert.equal(res.status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('worker: /v1/check validates the proxy parameter', async () => {
  for (const q of [
    '',
    'proxy=',
    'proxy=nonsense',
    'proxy=1.2.3.4:99999',
    'proxy=10.0.0.1:8080',
    'proxy=1.2.3.4:80&proto=telnet',
  ]) {
    const res = await worker.fetch(req(`/v1/check?${q}`), env);
    assert.equal(res.status, 400, `${q || '(empty)'} must be a 400`);
  }
});

test('worker: /v1/check rejects non-routable addresses', async () => {
  const res = await worker.fetch(req('/v1/check?proxy=192.168.1.1:8080'), env);
  assert.equal(res.status, 400);
  assert.match(((await res.json()) as { error: string }).error, /not routable/);
});

test('worker: /v1/check is never cached', async () => {
  // the sockets module only exists in workerd, so the route answers 501 here,
  // but the no-store header must already be in place
  const res = await worker.fetch(req('/v1/check?proxy=45.10.0.1:1080&proto=socks5'), env);
  assert.equal(res.headers.get('cache-control'), 'no-store');
  assert.equal([501, 200].includes(res.status), true, `unexpected ${res.status}`);
});
