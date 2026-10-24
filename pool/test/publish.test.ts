import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { publicationGuard } from '../src/publish/guard.js';
import { renderAll, qualitySort, toPublished } from '../src/publish/render.js';
import {
  newRecord,
  applyResult,
  percentile,
  uptimePct,
  type CheckResultRecord,
  type ProxyRecord,
} from '../src/store/types.js';

const mk = (over: Partial<CheckResultRecord> = {}): CheckResultRecord => ({
  protocol: 'socks5',
  host: '1.2.3.4',
  port: 1080,
  alive: true,
  latencyMs: 900,
  remoteIp: '1.2.3.4',
  anonymity: 'elite',
  tlsIssuer: null,
  tlsMitm: false,
  supportsTls: true,
  error: null,
  checkedAt: Date.now(),
  seenBy: ['src-a'],
  ...over,
});

const rec = (over: Partial<ProxyRecord> = {}): ProxyRecord => ({
  ...newRecord(mk()),
  ...over,
});

test('renderAll writes all artifacts with sane content', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'opp-render-'));
  const now = Date.now();
  // US gets six entries (shard threshold is 5), BR and DE stay under it
  const usRecords = Array.from({ length: 6 }, (_, i) =>
    rec({
      key: `http://10.0.0.${i}:8080`,
      protocol: 'http',
      host: `10.0.0.${i}`,
      port: 8080,
      country: 'US',
      anonymity: 'anonymous',
      latencyMs: 400 + i,
    }),
  );
  // A stale shard from an earlier generation must not survive this render.
  fs.mkdirSync(path.join(dir, 'country'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'country', 'DE.txt'), 'http://1.1.1.1:80\n');
  fs.writeFileSync(path.join(dir, 'country', 'ZZ.txt'), 'http://2.2.2.2:80\n');
  const report = renderAll(
    [
      rec({
        key: 'socks5://1.2.3.4:1080',
        protocol: 'socks5',
        host: '1.2.3.4',
        port: 1080,
        country: 'BR',
        asn: 15169,
        org: 'Google',
        anonymity: 'elite',
        latencyMs: 300,
      }),
      ...usRecords,
      rec({
        key: 'socks4://9.9.9.9:1080',
        protocol: 'socks4',
        host: '9.9.9.9',
        port: 1080,
        country: 'DE',
        anonymity: 'transparent',
        latencyMs: 200,
      }),
      rec({ key: 'socks5://7.7.7.7:1080', protocol: 'socks5', host: '7.7.7.7', port: 1080, lastOk: null }),
    ],
    { dataDir: dir, topN: 2, generatedAt: now, publishHistory: false },
  );
  try {
    assert.equal(report.total, 8, 'records with lastOk=null are skipped');
    const all = fs.readFileSync(path.join(dir, 'all.txt'), 'utf8').trim().split('\n');
    assert.equal(all.length, 8);
    assert.equal(all[0], 'socks5://1.2.3.4:1080', 'elite sorts first');
    const socks5 = fs.readFileSync(path.join(dir, 'socks5.txt'), 'utf8').trim().split('\n');
    assert.deepEqual(socks5, ['socks5://1.2.3.4:1080']);
    // every country with >= 5 entries is sharded; DE (single entry) is not
    assert.equal(fs.existsSync(path.join(dir, 'country/US.txt')), true);
    assert.equal(fs.readFileSync(path.join(dir, 'country/US.txt'), 'utf8').trim().split('\n').length, 6);
    assert.equal(fs.existsSync(path.join(dir, 'country/DE.txt')), false);
    assert.equal(fs.existsSync(path.join(dir, 'country/XX.txt')), false);
    assert.equal(fs.existsSync(path.join(dir, 'country/ZZ.txt')), false, 'stale shard removed');
    const top = fs.readFileSync(path.join(dir, 'top2.txt'), 'utf8').trim().split('\n');
    assert.equal(top.length, 2);
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
    assert.equal(manifest.count, 8);
    assert.equal(manifest.files.some((f: { name: string }) => f.name === 'all.txt'), true);
    assert.equal(manifest.files.every((f: { sha256: string }) => f.sha256.length === 64), true);
    const stats = JSON.parse(fs.readFileSync(path.join(dir, 'stats.json'), 'utf8'));
    assert.equal(stats.total, 8);
    assert.equal(stats.byProtocol.socks5, 1);
    for (const b of ['alive', 'total', 'http', 'socks4', 'socks5', 'updated']) {
      assert.equal(fs.existsSync(path.join(dir, 'badges', `${b}.json`)), true);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('publication refuses unproven exits and the checker itself', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pool-publish-exit-'));
  try {
    const report = renderAll(
      [
        rec({ host: '1.1.1.1', remoteIp: null }),
        rec({ host: '2.2.2.2', remoteIp: '203.0.113.9' }),
        rec({ host: '3.3.3.3', remoteIp: '193.34.212.154' }),
      ],
      {
        dataDir: dir,
        topN: 10,
        generatedAt: Date.now(),
        publishHistory: false,
        serverIp: '193.34.212.154',
      },
    );
    assert.equal(report.total, 1, 'only the proven third-party exit is published');
    const all = fs.readFileSync(path.join(dir, 'all.txt'), 'utf8').trim();
    assert.equal(all, 'socks5://2.2.2.2:1080');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('publication guard keeps the previous files on a >50% collapse', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pool-guard-'));
  try {
    assert.equal(publicationGuard(dir, 10).open, false);
    fs.writeFileSync(
      path.join(dir, 'meta.json'),
      JSON.stringify({ counts: { published: 1000 } }),
      'utf8',
    );
    assert.equal(publicationGuard(dir, 499).open, true);
    assert.equal(publicationGuard(dir, 500).open, false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('qualitySort prefers elite, then non-mitm, then latency', () => {
  const a = toPublished(rec({ anonymity: 'elite', latencyMs: 800 }));
  const b = toPublished(rec({ anonymity: 'anonymous', latencyMs: 100 }));
  const c = toPublished(rec({ anonymity: 'elite', latencyMs: 900, tlsMitm: true }));
  const d = toPublished(rec({ anonymity: 'elite', latencyMs: 800 }));
  assert.ok(qualitySort(a, b) < 0);
  assert.ok(qualitySort(d, c) < 0);
  assert.equal(qualitySort(a, d), 0);
});

test('uptime from an older checker is unknown until three new checks', () => {
  const old = rec({ checkerVersion: undefined, okChecks: 10, uptime30d: [10, 10] });
  assert.equal(toPublished(old).uptime30d, null);
  let next = applyResult(old, mk());
  assert.equal(toPublished(next).uptime30d, null, 'first proof is not history');
  next = applyResult(next, mk({ checkedAt: next.lastCheck + 1 }));
  next = applyResult(next, mk({ checkedAt: next.lastCheck + 1 }));
  assert.equal(toPublished(next).uptime30d, 100);
});

test('applyResult drops a stale grade when the new check cannot grade anonymity', () => {
  const base = rec({ anonymity: 'elite' });
  const next = applyResult(
    base,
    mk({ alive: true, anonymity: 'unknown', checkedAt: base.checkedAt + 10 }),
  );
  assert.equal(next.anonymity, 'unknown');
});

test('toPublished does not fabricate 100% uptime for a new record', () => {
  let record = rec();
  assert.equal(record.okChecks, 1);
  for (const window of ['uptime1h', 'uptime24h', 'uptime7d', 'uptime30d'] as const) {
    assert.equal(toPublished(record)[window], null);
  }
  record = applyResult(record, mk({ checkedAt: record.checkedAt + 10 }));
  assert.equal(record.okChecks, 2);
  assert.equal(toPublished(record).uptime30d, null, 'still fewer than three successes');
  record = applyResult(record, mk({ checkedAt: record.checkedAt + 10 }));
  assert.equal(record.okChecks, 3);
  assert.equal(toPublished(record).uptime30d, 100);
});

test('rolling windows and percentiles behave', () => {
  const base = newRecord(mk());
  const ok = applyResult(base, mk({ alive: false, checkedAt: base.checkedAt + 10, latencyMs: null }));
  const bad = applyResult(ok, mk({ alive: true, checkedAt: ok.checkedAt + 10 }));
  assert.equal(uptimePct(base.uptime30d), 100);
  assert.ok(uptimePct(ok.uptime30d)! < 100);
  assert.equal(bad.fails, 0);
  assert.equal(bad.okChecks, 2);
  assert.equal(percentile([1, 2, 3, 4], 50), 2);
  assert.equal(percentile([], 50), null);
});
