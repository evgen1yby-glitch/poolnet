import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildRoast, renderRoast } from '../src/cli/roast.js';
import type { Benchmark, HistoryPoint } from '../src/benchmark/index.js';

const bench: Benchmark = {
  generatedAt: 1,
  cycle: { parsed: 3_600_000, unique: 733_000, sampled: 4000, alive: 1315 },
  sources: [
    {
      id: 'honest-one',
      candidates: 100,
      alive: 80,
      liveRate: 0.8,
      published: 100,
      medianLatency: 400,
      eliteRate: 0.5,
      staleDays: 1,
    },
    {
      id: 'big-lie',
      candidates: 120,
      alive: 10,
      liveRate: 0.0833,
      published: 100_000,
      medianLatency: 9000,
      eliteRate: 0,
      staleDays: 300,
    },
    {
      id: 'small-dead',
      candidates: 90,
      alive: 0,
      liveRate: 0,
      published: 90,
      medianLatency: null,
      eliteRate: null,
      staleDays: null,
    },
  ],
  ranks: { 'honest-one': 1, 'big-lie': 2, 'small-dead': 3 },
};

const history: HistoryPoint[] = [
  { ts: 1, ranks: { 'honest-one': 3, 'big-lie': 1 }, live: {} },
  { ts: 2, ranks: { 'honest-one': 1, 'big-lie': 2 }, live: {} },
];

test('buildRoast: finds the biggest gap and the most honest source', () => {
  const r = buildRoast(bench, history, 1_700_000_000_000);
  assert.equal(r.biggestFraud!.id, 'big-lie');
  assert.equal(r.mostHonest!.id, 'honest-one');
  assert.equal(r.rising[0]!.id, 'honest-one');
  assert.equal(r.rising[0]!.from, 3);
  assert.equal(r.falling[0]!.id, 'big-lie');
  assert.equal(r.stalest!.id, 'big-lie');
  assert.equal(r.freshest!.id, 'honest-one');
});

test('buildRoast: ignores too-small sources for the fraud award', () => {
  const r = buildRoast(bench, [], 1);
  assert.notEqual(r.biggestFraud!.id, 'small-dead', '90 entries is noise, not a scandal');
  assert.equal(r.rising.length, 0);
});

test('buildRoast: rank movement is ordered by the size of the move', () => {
  // c climbed 8 places, b climbed 3, a climbed 1 - the order must reflect that
  const hist: HistoryPoint[] = [
    { ts: 1, ranks: { a: 10, b: 10, c: 10 }, live: {} },
    { ts: 2, ranks: { a: 9, b: 7, c: 2 }, live: {} },
  ];
  const r = buildRoast(bench, hist, 1);
  assert.deepEqual(
    r.rising.map((x) => x.id),
    ['c', 'b', 'a'],
  );
});

test('buildRoast: a small source never wins least-alive', () => {
  // 90 published entries at 0% is noise next to a 20k list at 1%
  const b: Benchmark = {
    ...bench,
    sources: [
      {
        id: 'tiny-zero',
        candidates: 15,
        alive: 0,
        liveRate: 0,
        published: 90,
        medianLatency: null,
        eliteRate: null,
        staleDays: null,
      },
      {
        id: 'big-weak',
        candidates: 120,
        alive: 1,
        liveRate: 1 / 120,
        published: 20_000,
        medianLatency: 50,
        eliteRate: 0,
        staleDays: null,
      },
    ],
  };
  const r = buildRoast(b, [], 1);
  assert.equal(r.leastAlive!.id, 'big-weak');
});

test('renderRoast: reports published vs checked, never one for the other', () => {
  const r = buildRoast(bench, [], 1_700_000_000_000);
  const md = renderRoast(r);
  assert.match(md, /big-lie\*\* published 100,000 entries/);
  assert.match(md, /120 of which this pipeline checked/);
  assert.match(md, /10 answered/);
});

test('renderRoast: mentions the numbers and the honesty line', () => {
  const md = renderRoast(buildRoast(bench, history, 1_700_000_000_000));
  assert.match(md, /3,600,000 lines/);
  assert.match(md, /big-lie/);
  assert.match(md, /own checks, not from any source/);
});
