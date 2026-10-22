import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseGfp } from '../src/parse/gfp.js';

const record = (over: Record<string, unknown> = {}) => ({
  id: 'x',
  https: true,
  google: true,
  protocol: 'socks5',
  ip: '1.2.3.4',
  port: 1080,
  user: '',
  passwd: '',
  countryCode: 'US',
  region: 'California',
  asnNumber: '40065',
  asnName: '40065',
  anonymity: 'HIA',
  uptime: 77,
  responseTime: 2.69,
  lastAliveAt: '2026-10-14T15:45:50.001Z',
  proxyUrl: 'socks5://1.2.3.4:1080',
  ...over,
});

test('parseGfp: keeps supported protocols with their credentials', () => {
  const json = JSON.stringify([
    record(),
    record({ protocol: 'http', ip: '5.6.7.8', port: 8080, user: 'alice', passwd: 's3cret' }),
    record({ protocol: 'https', ip: '9.9.9.9', port: 443 }),
    record({ protocol: 'socks4', ip: '8.8.4.4', port: 4145 }),
  ]);
  const out = parseGfp(json);
  assert.equal(out.length, 4);
  assert.deepEqual(out[1], {
    protocol: 'http',
    host: '5.6.7.8',
    port: 8080,
    source: '',
    user: 'alice',
    pass: 's3cret',
  });
});

test('parseGfp: drops vmess/vless — real proxies, unsupported protocols', () => {
  const json = JSON.stringify([
    record({ protocol: 'vmess', ip: '129.146.143.80', port: 48111, user: 'd4603cc2-e0ee-4651-83f5-1db5b7168177' }),
    record({ protocol: 'vless', ip: '3.39.4.109', port: 18967, user: '814bd064-544d-4255-a070-5705c03f6da9' }),
    record({ protocol: 'trojan', ip: '1.1.1.1', port: 443 }),
    record({ protocol: 'socks5', ip: '2.2.2.2', port: 1080 }),
  ]);
  const out = parseGfp(json);
  assert.equal(out.length, 1);
  assert.equal(out[0]!.host, '2.2.2.2');
});

test('parseGfp: https is mapped to http (we probe with CONNECT)', () => {
  const out = parseGfp(JSON.stringify([record({ protocol: 'https', ip: '3.3.3.3', port: 3128 })]));
  assert.equal(out[0]!.protocol, 'http');
});

test('parseGfp: rejects junk rows', () => {
  const json = JSON.stringify([
    record({ ip: '127.0.0.1' }),
    record({ ip: '0.0.0.0' }),
    record({ ip: '999.1.1.1' }),
    record({ port: 99999 }),
    { ip: '1.2.3.4' },
    { protocol: 'socks5', port: 1080 },
    null,
  ]);
  assert.equal(parseGfp(json).length, 0);
});

test('parseGfp: invalid json yields empty', () => {
  assert.equal(parseGfp('<html>nope</html>').length, 0);
  assert.equal(parseGfp('{"data":[]}').length, 0);
});

// --- per-source sampling: small sources must not be starved by the stride ---
import { selectCycleSample } from '../src/cli/fetch.js';

test('selectCycleSample: every source gets its guaranteed slice', () => {
  const big = Array.from({ length: 500_000 }, (_, i) => `http://10.0.${Math.floor(i / 256)}.${i % 256}:80`);
  const tiny = ['socks5://1.2.3.4:1080', 'socks5://5.6.7.8:1080', 'socks5://9.9.9.9:1080'];
  const bySource = new Map([
    ['big', big],
    ['tiny', tiny],
  ]);
  const picked = selectCycleSample(bySource, 5000, 100);
  for (const k of tiny) assert.ok(picked.has(k), `tiny source starved: ${k}`);
  assert.ok(picked.size <= 5000);
});

test('selectCycleSample: a smaller-than-minimum source contributes everything it has', () => {
  const bySource = new Map([
    ['a', ['1.1.1.1:80']],
    ['b', ['2.2.2.2:80', '3.3.3.3:80']],
  ]);
  const picked = selectCycleSample(bySource, 100, 50);
  assert.deepEqual([...picked].sort(), ['1.1.1.1:80', '2.2.2.2:80', '3.3.3.3:80']);
});

test('selectCycleSample: cap is respected and never exceeded', () => {
  const bySource = new Map(
    Array.from({ length: 10 }, (_, i) => [`s${i}`, Array.from({ length: 100 }, (_, j) => `${i}.${j}`)]),
  );
  for (const cap of [1, 5, 37, 500, 10_000]) {
    assert.ok(selectCycleSample(bySource, cap, 5).size <= Math.max(cap, 1), `cap ${cap} exceeded`);
  }
});

test('selectCycleSample: fair share respects the cap across many sources', () => {
  // 177 sources like production: per-source minimum × sources must not
  // silently evict the sources at the end of the registry
  const bySource = new Map<string, string[]>();
  for (let i = 0; i < 177; i++) {
    const keys = Array.from({ length: i === 176 ? 33 : 5000 }, (_, j) => `${i}:${j}`);
    bySource.set(`s${i}`, keys);
  }
  const picked = selectCycleSample(bySource, 1500, 120);
  assert.ok(picked.size <= 1500);
  const last = [...bySource.get('s176')!];
  const fromLast = last.filter((k) => picked.has(k));
  assert.ok(fromLast.length >= 8, `last source got only ${fromLast.length}`);
  for (const src of ['s0', 's1', 's175']) {
    const keys = [...bySource.get(src)!];
    assert.ok(
      keys.some((k) => picked.has(k)),
      `${src} starved`,
    );
  }
});
