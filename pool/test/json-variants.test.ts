import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseJsonSource } from '../src/parse/json.js';

test('json: geonode shape still parses', () => {
  const json = JSON.stringify({
    data: [
      { ip: '1.2.3.4', port: 1080, protocols: ['socks5'] },
      { ip: '5.6.7.8', port: 8080, protocols: ['http', 'socks5'] },
      { ip: '9.9.9.9', port: 3128, protocols: ['socks4'] },
    ],
  });
  const out = parseJsonSource(json, 'http');
  assert.equal(out.length, 3);
  assert.equal(out[0]!.protocol, 'socks5');
  assert.equal(out[1]!.protocol, 'socks5');
  assert.equal(out[2]!.protocol, 'socks4');
});

test('json: charlespikachu shape uses singular protocol, case-insensitive', () => {
  const json = JSON.stringify({
    updated_at: '2026-11-19 02:24:40 UTC',
    count: 4,
    data: [
      { ip: '103.231.78.36', port: 4145, protocol: 'Socks5', country: 'US' },
      { ip: '103.51.223.133', port: 8080, protocol: 'Http', country: 'US' },
      { ip: '1.1.1.1', port: 1080, protocol: 'socks5' },
    ],
  });
  const out = parseJsonSource(json, 'socks5');
  assert.equal(out.length, 3);
  assert.equal(out[0]!.protocol, 'socks5');
  assert.equal(out[1]!.protocol, 'http');
  assert.equal(out[2]!.protocol, 'socks5');
});

test('json: combined protocol strings resolve by socks5 > http > socks4', () => {
  const json = JSON.stringify({
    data: [
      { ip: '1.1.1.1', port: 1, protocol: 'Http, Socks5' },
      { ip: '2.2.2.2', port: 2, protocol: 'Http, Socks4' },
      { ip: '3.3.3.3', port: 3, protocol: 'Socks4, Socks5' },
      { ip: '4.4.4.4', port: 4, protocol: 'Http, Https' },
    ],
  });
  const out = parseJsonSource(json, 'socks4');
  assert.equal(out[0]!.protocol, 'socks5');
  assert.equal(out[1]!.protocol, 'http');
  assert.equal(out[2]!.protocol, 'socks5');
  assert.equal(out[3]!.protocol, 'http');
});

test('json: mauricegift shape is a string array of ip:port', () => {
  const json = JSON.stringify({
    proxies: ['103.197.241.209:1080', 'socks5://166.62.35.102:45775', 'not-a-proxy'],
  });
  const out = parseJsonSource(json, 'socks5');
  assert.equal(out.length, 2);
  assert.deepEqual(out[0], { protocol: 'socks5', host: '103.197.241.209', port: 1080, source: '' });
  assert.equal(out[1]!.host, '166.62.35.102');
});

test('json: proxytee shape uses host/proxy_type/types', () => {
  const json = JSON.stringify({
    proxies: [
      {
        host: '67.201.35.145',
        port: 4145,
        proxy_type: 'SOCKS5',
        types: [{ type: 'SOCKS5' }],
      },
      {
        host: '5.6.7.8',
        port: 8080,
        proxy_type: 'HTTP',
        types: [{ type: 'HTTP' }],
      },
    ],
  });
  const out = parseJsonSource(json, 'socks5');
  assert.equal(out.length, 2);
  assert.deepEqual(out[0], { protocol: 'socks5', host: '67.201.35.145', port: 4145, source: '' });
  assert.equal(out[1]!.protocol, 'http');
});

test('json: entries without a protocol fall back to the declared default', () => {
  const json = JSON.stringify({
    proxies: [{ host: '8.8.8.8', port: 1080 }],
  });
  assert.equal(parseJsonSource(json, 'socks5')[0]!.protocol, 'socks5');
  assert.equal(parseJsonSource(json, 'http')[0]!.protocol, 'http');
});

test('json: rejects private, malformed and out-of-range rows', () => {
  const json = JSON.stringify({
    data: [
      { ip: '127.0.0.1', port: 1080, protocol: 'socks5' },
      { ip: '10.0.0.1', port: 1080, protocol: 'socks5' },
      { ip: '999.1.1.1', port: 1080, protocol: 'socks5' },
      { ip: '1.2.3.4', port: 99999, protocol: 'socks5' },
      { ip: '1.2.3.4', port: 'nope', protocol: 'socks5' },
      { ip: '1.2.3.4', protocol: 'socks5' },
      null,
    ],
    proxies: ['127.0.0.1:1080', '1.2.3.4:70000'],
  });
  assert.equal(parseJsonSource(json, 'socks5').length, 0);
});

test('json: invalid or non-object payloads yield empty', () => {
  assert.equal(parseJsonSource('not json', 'http').length, 0);
  assert.equal(parseJsonSource('[]', 'http').length, 0);
  assert.equal(parseJsonSource('{"foo":[]}', 'http').length, 0);
});