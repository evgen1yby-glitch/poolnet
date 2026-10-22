import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseJsonSource } from '../src/parse/json.js';

// Shape captured from roundproxies' /api/get-free-proxies: port as a string,
// protocols array. Total 3,947 over 8 pages of 500.
const API = JSON.stringify({
  data: [
    { ip: '45.84.13.153', port: '1080', protocols: ['socks5'], anonymityLevel: 'elite', latency: 58.4 },
    { ip: '1.20.178.212', port: '443', protocols: ['http'], anonymityLevel: 'transparent' },
    { ip: '115.74.153.148', port: '1080', protocols: ['socks4'], anonymityLevel: 'anonymous' },
    { ip: '9.9.9.9', port: 8080, protocols: ['http'] },
    { ip: '127.0.0.1', port: '1080', protocols: ['socks5'] },
  ],
  total: 3947,
  page: 1,
  limit: 500,
});

test('parseJsonSource: roundproxies payload with string ports', () => {
  const out = parseJsonSource(API, 'http');
  assert.equal(out.length, 4);
  assert.deepEqual(out[0], { protocol: 'socks5', host: '45.84.13.153', port: 1080, source: '' });
  assert.equal(out[1]!.protocol, 'http');
  assert.equal(out[1]!.port, 443);
  assert.equal(out[2]!.protocol, 'socks4');
});

test('parseJsonSource: numeric ports still work (geonode shape)', () => {
  const geonode = JSON.stringify({ data: [{ ip: '1.2.3.4', port: 1080, protocols: ['socks5'] }] });
  assert.deepEqual(parseJsonSource(geonode, 'http'), [{ protocol: 'socks5', host: '1.2.3.4', port: 1080, source: '' }]);
});
