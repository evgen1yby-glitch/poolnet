import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkProxyOnDemand } from '../workers/api/check.js';

const enc = new TextEncoder();

/**
 * A stub socket: every write is recorded, and the responses array is served
 * in order on the readable side. A TransformStream in this position
 * backpressures before the reader ever runs (it would hang the checker under
 * test), so two plain streams behave exactly like the real socket pair.
 */
function stubSocket(responses: Array<string | Uint8Array>) {
  const dec = new TextDecoder();
  const written: string[] = [];
  const writable = new WritableStream({
    write(chunk) {
      written.push(dec.decode(chunk, { stream: true }));
    },
  });
  const readable = new ReadableStream({
    start(controller) {
      for (const r of responses) controller.enqueue(typeof r === 'string' ? enc.encode(r) : r);
      controller.close();
    },
  });
  return { socket: { writable, readable, close: async () => {} }, written };
}

const ECHO = (origin: string) =>
  `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength('{"origin":"' + origin + '"}')}\r\nConnection: close\r\n\r\n{"origin":"${origin}"}`;

const SOCKS_OK = '\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00';

test('check: a working socks5 proxy is alive and reports the origin', async () => {
  const { socket, written } = stubSocket(['\x05\x00', SOCKS_OK, ECHO('203.0.113.9')]);
  const out = await checkProxyOnDemand({
    proxy: { protocol: 'socks5', host: '45.10.0.1', port: 1080 },
    connect: () => socket,
    targetUrl: 'http://echo.test/get',
  });
  assert.equal(out.alive, true, out.error ?? '');
  assert.equal(out.remoteIp, '203.0.113.9');
  assert.ok(out.latencyMs !== null && out.latencyMs >= 0);
  const bytes = (i: number) => [...written[i]!].map((c) => c.charCodeAt(0));
  assert.deepEqual(bytes(0), [0x05, 0x01, 0x00], 'the greeting');
  assert.equal(bytes(1)[0], 0x05, 'the socks5 connect request');
  assert.equal(bytes(1)[3], 0x01, 'the IPv4 address type');
  assert.match(written[2]!, /GET \/get HTTP\/1\.1/, 'the echo request');
});

test('check: a proxy that refuses CONNECT is reported dead with the reason', async () => {
  const { socket } = stubSocket(['HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n', ECHO('203.0.113.9')]);
  const out = await checkProxyOnDemand({
    proxy: { protocol: 'http', host: '45.10.0.2', port: 3128 },
    connect: () => socket,
    targetUrl: 'http://echo.test/get',
  });
  assert.equal(out.alive, false);
  assert.match(out.error!, /CONNECT -> 403/);
});

test('check: a non-200 from the target is not "alive"', async () => {
  const { socket } = stubSocket([
    '\x05\x00',
    SOCKS_OK,
    'HTTP/1.1 429 Too Many Requests\r\nContent-Length: 0\r\nConnection: close\r\n\r\n',
  ]);
  const out = await checkProxyOnDemand({
    proxy: { protocol: 'socks5', host: '45.10.0.3', port: 1080 },
    connect: () => socket,
    targetUrl: 'http://echo.test/get',
  });
  assert.equal(out.alive, false);
  assert.match(out.error!, /HTTP 429/);
});

test('check: a silent proxy is dead, never alive', async () => {
  const { socket } = stubSocket(['\x05\x00']); // greeting answered, then the stream ends
  const out = await checkProxyOnDemand({
    proxy: { protocol: 'socks5', host: '45.10.0.4', port: 1080 },
    connect: () => socket,
    targetUrl: 'http://echo.test/get',
    timeoutMs: 800,
  });
  assert.equal(out.alive, false);
  assert.ok(out.error, 'the failure has a reason');
});
