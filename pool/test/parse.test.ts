import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseProxyLine } from '../src/parse/plain.js';
import { parseJsonSource } from '../src/parse/json.js';

test('parseProxyLine: bare ip:port uses the declared protocol', () => {
  assert.deepEqual(parseProxyLine('1.2.3.4:8080', 'http'), {
    protocol: 'http',
    host: '1.2.3.4',
    port: 8080,
    source: '',
  });
});

test('parseProxyLine: scheme overrides the declared protocol', () => {
  assert.deepEqual(parseProxyLine('socks5://1.2.3.4:1080', 'http'), {
    protocol: 'socks5',
    host: '1.2.3.4',
    port: 1080,
    source: '',
  });
  assert.deepEqual(parseProxyLine('http://1.2.3.4:3128', 'socks5'), {
    protocol: 'http',
    host: '1.2.3.4',
    port: 3128,
    source: '',
  });
});

// Regression: whole sources were dropped when every line carried a scheme
// (observable: proxifly returned 0 candidates from 47k lines).
test('parseProxyLine: https is mapped to http, socks4a to socks4', () => {
  assert.equal(parseProxyLine('https://1.2.3.4:443', 'socks5')?.protocol, 'http');
  assert.equal(parseProxyLine('socks4a://1.2.3.4:1080', 'http')?.protocol, 'socks4');
  assert.equal(parseProxyLine('socks4://1.2.3.4:1080', 'http')?.protocol, 'socks4');
});

test('parseProxyLine: credentials parse', () => {
  assert.deepEqual(parseProxyLine('socks5://user:secret@1.2.3.4:1080', 'http'), {
    protocol: 'socks5',
    host: '1.2.3.4',
    port: 1080,
    source: '',
    user: 'user',
    pass: 'secret',
  });
  assert.deepEqual(parseProxyLine('user:secret@1.2.3.4:8080', 'http'), {
    protocol: 'http',
    host: '1.2.3.4',
    port: 8080,
    source: '',
    user: 'user',
    pass: 'secret',
  });
});

test('parseProxyLine: tolerates annotation tails', () => {
  assert.deepEqual(parseProxyLine('170.239.207.241:999 CO-N-S! +', 'http'), {
    protocol: 'http',
    host: '170.239.207.241',
    port: 999,
    source: '',
  });
  assert.deepEqual(parseProxyLine('https://1.2.3.4:443 elite', 'socks5'), {
    protocol: 'http',
    host: '1.2.3.4',
    port: 443,
    source: '',
  });
});

test('parseProxyLine: garbage is rejected', () => {
  for (const line of [
    '',
    '# comment',
    'not-a-proxy',
    '1.2.3.4',
    '1.2.3.4:99999',
    '999.1.1.1:8080',
    'socks5://host.example:1080',
    'socks6://1.2.3.4:1080',
  ]) {
    assert.equal(parseProxyLine(line, 'http'), null, `expected null for: ${line}`);
  }
});

test('parseJsonSource: geonode-shaped payload', () => {
  const json = JSON.stringify({
    data: [
      { ip: '1.2.3.4', port: 1080, protocols: ['socks5'] },
      { ip: '5.6.7.8', port: 8080, protocols: ['http', 'socks5'] },
      { ip: '9.9.9.9', port: 3128, protocols: ['socks4'] },
      { ip: '0.0.0.0', port: 1080, protocols: ['socks5'] },
      { ip: '1.2.3.4' },
    ],
  });
  const out = parseJsonSource(json, 'http');
  assert.equal(out.length, 3);
  assert.deepEqual(out[0], { protocol: 'socks5', host: '1.2.3.4', port: 1080, source: '' });
  assert.equal(out[1]!.protocol, 'socks5'); // socks5 wins over http
  assert.equal(out[2]!.protocol, 'socks4');
});

test('parseJsonSource: invalid json yields empty', () => {
  assert.equal(parseJsonSource('not json', 'http').length, 0);
});
