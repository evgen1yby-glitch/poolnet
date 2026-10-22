import { randomInt } from 'node:crypto';
import { canonicalKey, hashString, type Candidate } from '../sources/types.js';

/**
 * Deduplicate by canonical key (protocol://host:port). The first source that
 * reported a candidate wins provenance, later ones are merged into a
 * `sources` set so multi-source proxies get a diversity bonus.
 */
export function dedupe(candidates: Candidate[]): Map<string, Candidate & { seenBy: string[] }> {
  const map = new Map<string, Candidate & { seenBy: string[] }>();
  for (const c of candidates) {
    const k = canonicalKey(c);
    const existing = map.get(k);
    if (existing) {
      if (!existing.seenBy.includes(c.source)) existing.seenBy.push(c.source);
      continue;
    }
    map.set(k, { ...c, seenBy: [c.source] });
  }
  return map;
}

/** Unbiased reservoir sample of n items. */
export function sample<T>(arr: T[], n: number): T[] {
  if (n >= arr.length) return arr.slice();
  const out: T[] = [];
  for (let i = 0; i < n; i++) out.push(arr[randomInt(0, arr.length)]!);
  return out;
}

/**
 * Deterministically assign an item to a shard, so a GitHub Actions matrix
 * covers the candidate space without coordination.
 */
export function shardOf(key: string, shardCount: number): number {
  if (shardCount <= 1) return 0;
  return hashString(key) % shardCount;
}

export function pickShard<T extends { key: string }>(items: T[], index: number, count: number): T[] {
  if (count <= 1) return items;
  return items.filter((i) => shardOf(i.key, count) === index);
}
