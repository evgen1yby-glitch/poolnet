import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { config, ensureDir } from '../config.js';
import { log } from '../log.js';
import { fetchAll } from '../sources/fetcher.js';
import { githubFileFreshness, parseGitHubRaw, STALE_DAYS } from '../sources/freshness.js';
import { loadSources } from '../sources/load.js';
import { parseSource } from '../parse/index.js';
import type { Candidate } from '../sources/types.js';

export interface CandidateEntry extends Candidate {
  seenBy: string[];
}

/**
 * Builds the cycle's candidate set.
 *
 * Every enabled source contributes a fair share of its entries first — a
 * guaranteed slice matters most for small sources, whose candidates would
 * otherwise never be picked by a uniform stride across a 700k universe (33
 * GFP entries in 731k is a 0.004% chance per cycle). The share is capped by
 * what the budget can hold across all sources, so the promise never breaks
 * the cap; whatever budget remains is filled with an even stride over the
 * rest of the universe.
 */
export function selectCycleSample(bySource: Map<string, string[]>, cap: number, perSourceMin: number): Set<string> {
  const selected = new Set<string>();
  if (cap <= 0 || bySource.size === 0) return selected;

  const stridePick = (keys: string[], n: number): string[] => {
    if (n >= keys.length) return keys.slice();
    const stride = keys.length / n;
    const out: string[] = [];
    for (let i = 0; out.length < n && i < keys.length; i++) {
      if (i >= out.length * stride) out.push(keys[i]!);
    }
    return out;
  };

  const share = Math.max(1, Math.min(perSourceMin, Math.floor(cap / bySource.size)));
  for (const [, keys] of bySource) {
    for (const k of stridePick(keys, share)) selected.add(k);
  }
  if (selected.size >= cap) return new Set([...selected].slice(0, cap));

  const restKeys: string[] = [];
  for (const [, keys] of bySource) {
    for (const k of keys) if (!selected.has(k)) restKeys.push(k);
  }
  const remaining = cap - selected.size;
  for (const k of stridePick(restKeys, Math.min(remaining, restKeys.length))) selected.add(k);
  return selected;
}

/** "proto://host:port" + provenance back into a candidate entry. */
function entryFrom(key: string, seenBy: string[]): CandidateEntry {
  const m = /^(https?|socks4|socks5):\/\/(.+):(\d+)$/.exec(key)!;
  const rawProto = m[1]!;
  const protocol: Candidate['protocol'] = rawProto === 'socks5' ? 'socks5' : rawProto === 'socks4' ? 'socks4' : 'http';
  return { protocol, host: m[2]!, port: Number(m[3]), source: seenBy[0]!, seenBy };
}

export interface FetchReport {
  startedAt: number;
  finishedAt: number;
  sources: Array<{
    id: string;
    status: number | null;
    ok: boolean;
    bytes: number;
    parsed: number;
    error?: string;
    /** header value, null when the source does not send one */
    lastModified: string | null;
    /** whole days since the source last updated, null when unknown */
    staleDays: number | null;
    /** last commit touching the file, from the GitHub API */
    lastCommitIso: string | null;
    lastCommitDays: number | null;
  }>;
  totalParsed: number;
  totalUnique: number;
  sampled: number;
}

export function candidatesPath(): string {
  return path.join(config().workDir, 'candidates.jsonl.gz');
}

export function readCandidates(file = candidatesPath()): CandidateEntry[] {
  if (!fs.existsSync(file)) return [];
  const text = zlib.gunzipSync(fs.readFileSync(file)).toString('utf8');
  return text
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line) as CandidateEntry);
}

export async function writeCandidates(entries: CandidateEntry[], file = candidatesPath()): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    const ws = zlib.createGzip();
    const out = fs.createWriteStream(tmp);
    ws.pipe(out);
    out.on('close', () => {
      try {
        fs.renameSync(tmp, file);
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    out.on('error', reject);
    ws.on('error', reject);
    for (const e of entries) ws.write(JSON.stringify(e) + '\n');
    ws.end();
  });
}

/** Command: fetch all sources, parse, dedupe, sample. */
export async function cmdFetch(): Promise<FetchReport> {
  const cfg = config();
  const startedAt = Date.now();
  const { sources: specs, skipped } = loadSources(cfg.sourcesFile);
  log.info(
    `fetch: ${specs.length} sources loaded${skipped.length ? `, ${skipped.length} skipped (missing env or malformed)` : ''}`,
  );

  const fetched = await fetchAll(specs);
  const sourceStats: FetchReport['sources'] = [];
  // Dedupe while parsing: the raw universe is millions of lines, and holding
  // every parsed line plus a map of uniques doubles the peak memory.
  const uniqueSeen = new Map<string, string[]>();
  let parsedCount = 0;
  let okSources = 0;

  for (const res of fetched) {
    const parsed = parseSource(res);
    parsedCount += parsed.length;
    for (const c of parsed) {
      const k = `${c.protocol}://${c.host}:${c.port}`;
      const seenBy = uniqueSeen.get(k);
      if (seenBy) {
        if (!seenBy.includes(c.source)) seenBy.push(c.source);
      } else {
        uniqueSeen.set(k, [c.source]);
      }
    }
    const lm = res.lastModified ? Date.parse(res.lastModified) : NaN;
    sourceStats.push({
      id: res.spec.id,
      status: res.status,
      ok: res.ok,
      bytes: res.body.length,
      parsed: parsed.length,
      error: res.error,
      lastModified: res.lastModified ?? null,
      // a source that answers 200 with a file untouched for months is the
      // dangerous kind: its health check passes while every entry is dead
      staleDays: Number.isFinite(lm) ? Math.floor((Date.now() - lm) / 86400000) : null,
      lastCommitIso: null,
      lastCommitDays: null,
    });
    if (res.ok && parsed.length === 0) {
      log.warn(`fetch: ${res.spec.id}: 200 OK but 0 candidates parsed - check the format`);
    }
    if (res.ok) okSources++;
    const days = sourceStats[sourceStats.length - 1]!.staleDays;
    if (days !== null && days > 90) {
      log.warn(`fetch: ${res.spec.id}: content last modified ${days} days ago — stale source`);
    }
  }

  if (okSources === 0) {
    // every source down (network partition, auth expiry, mass 403): the rest
    // of the cycle would republish the old pool as if it had just been checked
    throw new Error(`fetch: 0 of ${sourceStats.length} sources answered - aborting the cycle`);
  }

  // --- freshness pass -------------------------------------------------------
  // Independent check for the "200 but abandoned" case: for GitHub-hosted
  // sources we ask the API when the file last changed. Only runs when a token
  // is available (GitHub Actions always has one; local `gh auth token` too).
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || '';
  let fresh = fetched.filter((r) => r.ok && parseGitHubRaw(r.spec.url));
  if (fresh.length && !token) {
    // unauthenticated is 60 req/h — date only the largest sources, where
    // abandonment costs the most; CI has a token and dates all of them
    const bySize = [...fresh].sort((a, b) => b.body.length - a.body.length);
    fresh = bySize.slice(0, 20);
    log.info('fetch: freshness pass on the 20 largest sources — set GITHUB_TOKEN to date all');
  }
  if (fresh.length) {
    let cursor = 0;
    let dated = 0;
    const worker = async () => {
      while (cursor < fresh.length) {
        const res = fresh[cursor++]!;
        const f = await githubFileFreshness(res.spec.url, token);
        const stat = sourceStats.find((x) => x.id === res.spec.id);
        if (stat && f.days !== null) {
          stat.lastCommitIso = f.iso;
          stat.lastCommitDays = f.days;
          dated++;
          if (f.days > STALE_DAYS) {
            log.warn(`fetch: ${res.spec.id}: file untouched for ${f.days} days — stale source`);
          }
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(token ? 6 : 2, fresh.length) }, worker));
    log.info(`fetch: freshness — ${dated}/${fresh.length} GitHub sources dated`);
  }

  // Group candidate keys per source so small sources are not starved by the
  // even-stride sample: 33 GFP entries in a 731k universe would essentially
  // never be picked by chance — and they arrive pre-verified.
  const bySource = new Map<string, string[]>();
  for (const [k, seenBy] of uniqueSeen) {
    for (const src of seenBy) {
      const list = bySource.get(src);
      if (list) list.push(k);
      else bySource.set(src, [k]);
    }
  }

  const selected = selectCycleSample(bySource, cfg.maxNewPerCycle, cfg.perSourceMin);
  const entries: CandidateEntry[] = [];
  for (const k of selected) {
    const seenBy = uniqueSeen.get(k);
    if (seenBy) entries.push(entryFrom(k, seenBy));
  }

  await writeCandidates(entries);

  const report: FetchReport = {
    startedAt,
    finishedAt: Date.now(),
    sources: sourceStats,
    totalParsed: parsedCount,
    totalUnique: uniqueSeen.size,
    sampled: entries.length,
  };
  ensureDir(cfg.dataDir);
  fs.writeFileSync(path.join(cfg.dataDir, 'fetch-report.json'), JSON.stringify(report, null, 2) + '\n');
  log.info(
    `fetch: parsed=${parsedCount} unique=${uniqueSeen.size} sampled=${entries.length} ` +
      `okSources=${sourceStats.filter((s) => s.ok).length}/${sourceStats.length}`,
  );
  return report;
}
