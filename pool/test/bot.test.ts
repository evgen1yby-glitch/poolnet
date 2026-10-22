import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pickFrom, formatProxy, formatStats, parseCommand, resolveFilters } from '../bot/index.mjs';

const pool = [
  {
    id: 'a',
    protocol: 'socks5',
    host: '1.1.1.1',
    port: 1080,
    grade: 'elite',
    latency: 120,
    country: 'US',
    city: 'Dallas',
    uptime7d: 88,
    mitm: false,
  },
  {
    id: 'b',
    protocol: 'http',
    host: '2.2.2.2',
    port: 80,
    grade: 'anonymous',
    latency: 400,
    country: 'DE',
    city: null,
    uptime7d: 12,
    mitm: false,
  },
  {
    id: 'c',
    protocol: 'socks5',
    host: '3.3.3.3',
    port: 1080,
    grade: 'elite',
    latency: 900,
    country: 'US',
    city: null,
    uptime7d: null,
    mitm: true,
  },
  {
    id: 'd',
    protocol: 'socks4',
    host: '4.4.4.4',
    port: 1080,
    grade: 'transparent',
    latency: 200,
    country: 'FR',
    city: 'Paris',
    uptime7d: 50,
    mitm: false,
  },
];

test('parseCommand: /get socks5 US', () => {
  assert.deepEqual(parseCommand('/get socks5 US'), { name: 'get', protocol: 'socks5', country: 'US', size: null });
});

test('parseCommand: /get http and bare /get', () => {
  assert.equal(parseCommand('/get http').protocol, 'http');
  assert.equal(parseCommand('/get').protocol, null);
  assert.equal(parseCommand('/get DE').country, 'DE');
});

test('parseCommand: bot suffix and /top 5', () => {
  assert.equal(parseCommand('/stats@my_pool_bot').name, 'stats');
  assert.equal(parseCommand('/top 5').size, 5);
  // lowercase 2-letter tokens parse as candidates; resolveFilters decides
  assert.equal(parseCommand('/get xy').country, 'XY');
});

test('resolveFilters: unknown country codes become a typo, not a filter', () => {
  const known = ['US', 'DE', 'RU'];
  const ok = resolveFilters(parseCommand('/get socks5 US'), known);
  assert.deepEqual(ok, { protocol: 'socks5', country: 'US', typo: null });
  const typo = resolveFilters(parseCommand('/get xx'), known);
  assert.deepEqual(typo, { protocol: null, country: null, typo: 'XX' });
});

test('pickFrom: filters by protocol and country', () => {
  const us = pickFrom(pool, { protocol: 'socks5', country: 'US' });
  assert.ok(us !== null && ['a', 'c'].includes(us.id));
  assert.equal(pickFrom(pool, { protocol: 'http', country: 'US' }), null);
});

test('formatProxy: carries the essentials and warns about TLS', () => {
  const out = formatProxy(pool[2]!);
  assert.match(out, /socks5:\/\/3\.3\.3\.3:1080/);
  assert.match(out, /terminates TLS/);
  assert.match(out, /grade <b>elite<\/b>/);
});

test('formatStats: summarises the pool', () => {
  const meta = {
    total: 1215,
    byProtocol: { http: 900, socks5: 300, socks4: 15 },
    countries: [{ cc: 'US', n: 400 }],
    medianLatencyMs: 204,
    p95LatencyMs: 11277,
    sourcesOk: 177,
    sourcesTotal: 177,
    generatedIso: '2026-10-14T10:00:00.000Z',
  };
  const out = formatStats(meta);
  assert.match(out, /1,215/);
  assert.match(out, /177\/177/);
  assert.match(out, /2026-10-14 10:00/);
});
