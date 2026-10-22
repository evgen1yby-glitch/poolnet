import { test } from 'node:test';
import assert from 'node:assert/strict';
import { appendHistory, buildBenchmark, median, rankDelta, type HistoryPoint } from '../src/benchmark/index.js';

// raw = what each source published; aliveRows = what actually answered,
// keyed by canonical proxy key.
const raw = [
  // candidates = the sampled keys this pipeline checked; published = the list's full size
  { id: 'small-good', candidates: 50, published: 50, staleDays: 3, keys: ['socks5://1.1.1.1:1080'] },
  { id: 'big-bad', candidates: 120, published: 100_000, staleDays: null, keys: ['http://2.2.2.2:80'] },
  { id: 'stale-but-alive', candidates: 120, published: 2000, staleDays: 400, keys: ['socks4://3.3.3.3:1080'] },
];

const aliveRows = [
  { key: 'socks5://1.1.1.1:1080', latency: 200, grade: 'elite' }, // 1 of small-good's 50
  { key: 'http://2.2.2.2:80', latency: 900, grade: 'anonymous' }, // 1 of big-bad's 100k
  { key: 'socks4://3.3.3.3:1080', latency: 500, grade: 'transparent' },
];

test('buildBenchmark: ranks by live rate, not by raw volume', () => {
  const b = buildBenchmark(1, { parsed: 0, unique: 0, sampled: 0, alive: 3 }, raw, aliveRows);
  assert.deepEqual(
    b.sources.map((s) => s.id),
    ['small-good', 'big-bad', 'stale-but-alive'],
  );
  assert.equal(b.sources.find((s) => s.id === 'small-good')!.liveRate, 1 / 50);
  assert.equal(b.sources.find((s) => s.id === 'big-bad')!.liveRate, 1 / 120);
  assert.equal(b.sources.find((s) => s.id === 'big-bad')!.published, 100_000);
  assert.equal(b.ranks['small-good'], 1);
});

test('buildBenchmark: the published size never becomes the rate denominator', () => {
  // a 283k-entry list where 120 entries were sampled must be judged on the 120
  const oneHuge = [{ id: 'huge', candidates: 120, published: 283_598, staleDays: null, keys: ['http://1.1.1.1:80'] }];
  const b = buildBenchmark(1, { parsed: 0, unique: 0, sampled: 120, alive: 49 }, oneHuge, [
    { key: 'http://1.1.1.1:80', latency: 100, grade: 'elite' },
  ]);
  const huge = b.sources[0]!;
  assert.equal(huge.candidates, 120);
  assert.equal(huge.published, 283_598);
  assert.equal(huge.liveRate, 1 / 120);
});

test('buildBenchmark: a source is never credited for a proxy it did not publish', () => {
  // a proxy alive in two lists must not inflate either list past its own size
  const twoLists = [
    { id: 'a', candidates: 10, published: 10, staleDays: null, keys: ['socks5://9.9.9.9:1080'] },
    { id: 'b', candidates: 5, published: 5, staleDays: null, keys: ['socks5://9.9.9.9:1080'] },
  ];
  const b = buildBenchmark(1, { parsed: 0, unique: 0, sampled: 0, alive: 1 }, twoLists, [
    { key: 'socks5://9.9.9.9:1080', latency: 100, grade: 'elite' },
  ]);
  assert.equal(b.sources.find((s) => s.id === 'a')!.liveRate, 0.1);
  assert.equal(b.sources.find((s) => s.id === 'b')!.liveRate, 0.2);
  assert.ok(
    b.sources.every((s) => s.liveRate <= 1),
    'live rate must never exceed 100%',
  );
});

test('buildBenchmark: unknown key lists degrade to zero credit, never over 100%', () => {
  const b = buildBenchmark(1, { parsed: 0, unique: 0, sampled: 0, alive: 3 }, raw.slice(0, 1), aliveRows);
  const small = b.sources[0]!;
  assert.equal(small.alive, 1);
  assert.equal(small.liveRate, 1 / 50);
  assert.ok(small.liveRate <= 1);
});

test('buildBenchmark: per-source latency and elite share come from the checks', () => {
  const b = buildBenchmark(1, { parsed: 0, unique: 0, sampled: 0, alive: 3 }, raw, aliveRows);
  assert.equal(b.sources.find((s) => s.id === 'small-good')!.medianLatency, 200);
  assert.equal(b.sources.find((s) => s.id === 'small-good')!.eliteRate, 1);
  assert.equal(b.sources.find((s) => s.id === 'stale-but-alive')!.eliteRate, 0);
});

test('median: even and odd lengths', () => {
  assert.equal(median([]), null);
  assert.equal(median([5]), 5);
  assert.equal(median([1, 2, 3, 4]), 2.5);
  assert.equal(median([3, 1, 2]), 2);
});

test('appendHistory: caps at keep and preserves order', () => {
  let hist: HistoryPoint[] = [];
  for (let i = 0; i < 5; i++) {
    const b = buildBenchmark(
      i,
      { parsed: 0, unique: 0, sampled: 0, alive: 0 },
      [{ id: 'a', candidates: i + 1, staleDays: null, keys: [] }],
      [],
    );
    hist = appendHistory(hist, b, 3);
  }
  assert.equal(hist.length, 3);
  assert.deepEqual(
    hist.map((h) => h.ts),
    [2, 3, 4],
  );
});

test('rankDelta: positive means the source moved up', () => {
  const hist: HistoryPoint[] = [
    { ts: 1, ranks: { a: 3, b: 1 }, live: { a: 1, b: 9 } },
    { ts: 2, ranks: { a: 1, b: 5 }, live: { a: 9, b: 1 } },
  ];
  assert.equal(rankDelta(hist, 'a'), 2);
  assert.equal(rankDelta(hist, 'b'), -4);
  assert.equal(rankDelta(hist, 'unknown'), null);
  assert.equal(rankDelta([hist[0]!], 'a'), null);
});
