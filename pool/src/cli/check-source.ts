import path from 'node:path';
import { config } from '../config.js';
import { log } from '../log.js';
import { loadSources } from '../sources/load.js';
import { fetchAll } from '../sources/fetcher.js';
import { parseSource } from '../parse/index.js';
import { checkAll } from '../check/runner.js';
import { defaultTargets } from '../check/targets.js';
import { atomicWriteJson } from '../io/jsonl.js';
import { githubFileFreshness } from '../sources/freshness.js';

/**
 * Command: `opp check <source-id|url>`.
 *
 * Fetches ONE source, validates EVERY candidate it published and reports how
 * many are really alive — the honest answer to "is this list worth anything?".
 * Used to audit a source before trusting it, and to answer the same question
 * for sources already in the registry.
 */
export interface SourceCheckReport {
  id: string;
  url: string;
  fetchedAt: number;
  httpStatus: number | null;
  candidates: number;
  unique: number;
  checked: number;
  alive: number;
  liveRate: number;
  byProtocol: Record<string, number>;
  anonymity: Record<string, number>;
  medianLatency: number | null;
  p95Latency: number | null;
  staleDays: number | null;
  topErrors: Array<{ error: string; count: number }>;
  mitm: number;
  durationMs: number;
}

export async function cmdCheckSource(idOrUrl: string): Promise<SourceCheckReport> {
  const cfg = config();
  const started = Date.now();

  let spec = loadSources(cfg.sourcesFile).sources.find((s) => s.id === idOrUrl);
  if (!spec) {
    if (/^https?:\/\//.test(idOrUrl)) {
      spec = { id: 'adhoc', url: idOrUrl, format: 'plain' };
      // an arbitrary URL is more likely HTML than plain text
      const probe = await fetchAll([spec]);
      const body = probe[0]?.body ?? '';
      if (/<html|<table/i.test(body)) spec.format = 'html';
      else spec.format = 'plain';
    } else {
      throw new Error(`unknown source: ${idOrUrl} (not in ${cfg.sourcesFile} and not a URL)`);
    }
  }

  const { sources: registry } = loadSources(cfg.sourcesFile);
  const withAuth = registry.find((s) => s.id === spec!.id) ?? spec;

  const fetched = await fetchAll([withAuth]);
  const res = fetched[0];
  if (!res) {
    throw new Error(`source ${spec.id} is disabled (registry "enabled: false" or OPP_DISABLED_SOURCES)`);
  }
  if (!res.ok) {
    throw new Error(`source ${spec.id} fetch failed: ${res.error ?? 'unknown'} (HTTP ${res.status ?? 'n/a'})`);
  }

  const parsed = parseSource(res);
  const uniqueMap = new Map<string, (typeof parsed)[number]>();
  for (const c of parsed) uniqueMap.set(`${c.protocol}://${c.host}:${c.port}`, c);
  const unique = [...uniqueMap.values()];
  log.info(`check ${spec.id}: ${parsed.length} entries, ${unique.length} unique — validating all`);

  const targets = unique.map((c) => ({
    protocol: (c.protocol === 'https' ? 'http' : c.protocol) as 'http' | 'socks4' | 'socks5',
    host: c.host,
    port: c.port,
    user: c.user,
    pass: c.pass,
  }));
  const { results } = await checkAll(targets, {
    concurrency: cfg.checkConcurrency,
    timeoutMs: cfg.checkTimeoutMs,
    stage1TimeoutMs: cfg.stage1TimeoutMs,
    targets: defaultTargets(),
  });

  const alive = results.filter((r) => r.alive);
  const latencies = alive
    .map((r) => r.latencyMs)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  const median = latencies.length ? (latencies[Math.floor(latencies.length / 2)] ?? null) : null;
  const p95 = latencies.length
    ? (latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * 0.95))] ?? null)
    : null;

  const byProtocol: Record<string, number> = {};
  for (const r of alive) byProtocol[r.protocol] = (byProtocol[r.protocol] ?? 0) + 1;
  const anonymity: Record<string, number> = {};
  for (const r of alive) anonymity[r.anonymity] = (anonymity[r.anonymity] ?? 0) + 1;
  const errors = new Map<string, number>();
  for (const r of results) {
    if (r.alive || !r.error) continue;
    errors.set(r.error, (errors.get(r.error) ?? 0) + 1);
  }

  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  const fresh = await githubFileFreshness(spec.url, token);

  const report: SourceCheckReport = {
    id: spec.id,
    url: spec.url,
    fetchedAt: Date.now(),
    httpStatus: res.status,
    candidates: parsed.length,
    unique: unique.length,
    checked: results.length,
    alive: alive.length,
    liveRate: results.length ? alive.length / results.length : 0,
    byProtocol,
    anonymity,
    medianLatency: median,
    p95Latency: p95,
    staleDays: fresh.days,
    topErrors: [...errors.entries()]
      .map(([error, count]) => ({ error, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8),
    mitm: alive.filter((r) => r.tlsMitm).length,
    durationMs: Date.now() - started,
  };

  atomicWriteJson(path.join(cfg.dataDir, `sourcecheck-${spec.id}.json`), report);
  printReport(report);
  return report;
}

function printReport(r: SourceCheckReport): void {
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
  log.info(`check ${r.id}: ${r.alive}/${r.checked} alive (${pct(r.liveRate)})`);
  log.info(
    `  protocols ${JSON.stringify(r.byProtocol)} | anonymity ${JSON.stringify(r.anonymity)} | ` +
      `median ${r.medianLatency ?? '—'} ms | p95 ${r.p95Latency ?? '—'} ms | ` +
      `TLS-MITM ${r.mitm} | stale ${r.staleDays ?? '?'}d | ${(r.durationMs / 1000).toFixed(1)}s`,
  );
  for (const e of r.topErrors.slice(0, 5)) log.info(`  ×${e.count} ${e.error}`);
  if (r.alive === 0) log.warn(`check ${r.id}: NOTHING alive — this list is not usable`);
}
