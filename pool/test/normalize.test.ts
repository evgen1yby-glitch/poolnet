import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dedupe, sample, shardOf } from '../src/normalize/index.js';
import { canonicalKey, subnetOf, hashString } from '../src/sources/types.js';

const cand = (protocol: 'http' | 'socks5', host: string, port: number, source: string) => ({
  protocol,
  host,
  port,
  source,
});

test('dedupe merges same proxy from multiple sources and keeps provenance', () => {
  const map = dedupe([
    cand('socks5', '1.2.3.4', 1080, 'a'),
    cand('socks5', '1.2.3.4', 1080, 'b'),
    cand('http', '1.2.3.4', 1080, 'a'),
    cand('socks5', '5.6.7.8', 1080, 'c'),
  ]);
  assert.equal(map.size, 3);
  assert.deepEqual(map.get(canonicalKey({ protocol: 'socks5', host: '1.2.3.4', port: 1080 }))!.seenBy, ['a', 'b']);
});

test('shardOf is deterministic and covers the space', () => {
  const counts = new Map<number, number>();
  for (let i = 0; i < 10000; i++) {
    const s = shardOf(`socks5://1.2.3.${i}:1080`, 5);
    counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  assert.equal(counts.size, 5);
  for (const [_, n] of counts) {
    assert.ok(n > 1500 && n < 2500, `unbalanced shard: ${n}`);
  }
});

test('sample keeps the requested size', () => {
  const arr = Array.from({ length: 100 }, (_, i) => i);
  assert.equal(sample(arr, 10).length, 10);
  assert.equal(sample(arr, 500).length, 100);
});

test('hashString is stable', () => {
  assert.equal(hashString('http://1.2.3.4:8080'), hashString('http://1.2.3.4:8080'));
  assert.notEqual(hashString('a'), hashString('b'));
});

test('subnetOf groups /24s and passes through non-IPv4', () => {
  assert.equal(subnetOf('1.2.3.4'), '1.2.3');
  assert.equal(subnetOf('example.com'), 'example.com');
});
