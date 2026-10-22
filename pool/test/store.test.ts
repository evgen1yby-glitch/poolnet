import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { FsStore } from '../src/store/fs.js';
import type { CheckResultRecord } from '../src/store/types.js';

const res = (host: string, alive: boolean, over: Partial<CheckResultRecord> = {}): CheckResultRecord => ({
  protocol: 'socks5',
  host,
  port: 1080,
  alive,
  latencyMs: alive ? 500 : null,
  remoteIp: host,
  anonymity: 'elite',
  tlsIssuer: null,
  tlsMitm: false,
  supportsTls: true,
  error: alive ? null : 'timeout',
  checkedAt: Date.now(),
  seenBy: [],
  ...over,
});

test('FsStore: round-trips records through its snapshot', async () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-')), 'pool.json.gz');
  const a = new FsStore(file);
  await a.applyResults([res('1.2.3.4', true), res('5.6.7.8', false)]);
  await a.flush();

  const b = new FsStore(file);
  const pool = await b.loadPool();
  assert.equal(pool.size, 2);
  assert.equal(pool.get('socks5://1.2.3.4:1080')!.okChecks, 1);
  assert.equal(pool.get('socks5://5.6.7.8:1080')!.okChecks, 0);
});

test('FsStore: applyResult accumulates counters', async () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-')), 'pool.json.gz');
  const store = new FsStore(file);
  const now = Date.now();
  await store.applyResults([res('1.2.3.4', true, { checkedAt: now })]);
  await store.applyResults([res('1.2.3.4', true, { checkedAt: now + 5 })]);
  await store.applyResults([res('1.2.3.4', false, { checkedAt: now + 10 })]);
  const pool = await store.loadPool();
  const r = pool.get('socks5://1.2.3.4:1080')!;
  assert.equal(r.checks, 3);
  assert.equal(r.okChecks, 2);
  assert.equal(r.fails, 1);
  assert.equal(r.latencySamples.length, 2, 'null latency does not extend samples');
});

test('FsStore: pending skips fresh alive proxies and un-retried dead ones', async () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-')), 'pool.json.gz');
  const store = new FsStore(file);
  const now = Date.now();
  await store.applyResults([
    res('1.1.1.1', true, { checkedAt: now }),
    res('2.2.2.2', true, { checkedAt: now - 120 * 60_000 }), // alive but stale -> due
    res('3.3.3.3', false, { checkedAt: now - 60 * 60_000 }), // failed inside retry window -> skip
    res('4.4.4.4', false, { checkedAt: now - 24 * 3600_000 }), // failed long ago -> due
  ]);
  const pending = await store.selectPending({
    limit: 100,
    aliveAfterMs: 20 * 60_000,
    retryFailedAfterMs: 12 * 3600_000,
    maxRecords: 10_000,
  });
  const hosts = pending.map((p) => p.host).sort();
  assert.deepEqual(hosts, ['2.2.2.2', '4.4.4.4']);
});

test('FsStore: prune removes long-dead and over-cap records', async () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-')), 'pool.json.gz');
  const store = new FsStore(file);
  const now = Date.now();
  await store.applyResults([
    res('1.1.1.1', true, { checkedAt: now }),
    res('2.2.2.2', false, { checkedAt: now - 30 * 24 * 3600_000 }),
    res('3.3.3.3', false, { checkedAt: now - 30 * 24 * 3600_000 }),
  ]);
  const removed = await store.prune({ keepMax: 2, deadAfterMs: 7 * 24 * 3600_000 });
  assert.ok(removed >= 2);
  const pool = await store.loadPool();
  assert.ok(pool.size <= 2);
  assert.equal(pool.has('socks5://1.1.1.1:1080'), true);
});
