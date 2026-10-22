import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir } from '../config.js';
import { log } from '../log.js';
import { readJsonlGz, jsonlGzWriter, atomicWriteJson } from '../io/jsonl.js';
import { createStore } from '../store/index.js';
import { poolStatePath } from './validate.js';
import type { CheckResultRecord } from '../store/types.js';
import { geoLookup } from '../geo/index.js';
import { readCandidates } from './fetch.js';
import { subnetOfHost } from '../store/types.js';
import { renderAll } from '../publish/render.js';
import { appendHistory, buildBenchmark, type CycleStats, type HistoryPoint } from '../benchmark/index.js';

function medianLatencyOf(records: Array<{ latencyMs: number | null }>): number | null {
  const vals = records.map((r) => r.latencyMs).filter((v): v is number => v !== null);
  if (vals.length === 0) return null;
  const sorted = [...vals].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : Math.round((sorted[mid - 1]! + sorted[mid]!) / 2);
}

function topCountriesOf(records: Array<{ country: string | null }>, n: number): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const r of records) {
    if (!r.country) continue;
    counts.set(r.country, (counts.get(r.country) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);
}

export interface MergeReport {
  startedAt: number;
  finishedAt: number;
  shards: number;
  resultsIn: number;
  aliveIn: number;
  poolSize: number;
  published: number;
  byProtocol: Record<string, number>;
  pendingForNextRun: number;
  geoFilled: number;
  pruned: number;
  maxPerSubnet: number;
  aliveBySource: Record<string, number>;
  parsedBySource: Record<string, number>;
}

/** Read every results-<n>.jsonl.gz produced by matrix shards. */
export function readAllResults(workDir: string): CheckResultRecord[] {
  const files = fs
    .readdirSync(workDir)
    .filter((f) => /^results-\d+\.jsonl\.gz$/.test(f))
    .sort();
  const out: CheckResultRecord[] = [];
  for (const f of files) {
    out.push(...readJsonlGz<CheckResultRecord>(path.join(workDir, f)));
  }
  return out;
}

/**
 * Command: merge all shard results into the store, enrich, publish data/.
 * This is the single writer of the public artifacts.
 */
export async function cmdMerge(): Promise<MergeReport> {
  const cfg = config();
  const startedAt = Date.now();
  ensureDir(cfg.workDir);
  ensureDir(cfg.dataDir);

  const results = readAllResults(cfg.workDir);
  const aliveIn = results.filter((r) => r.alive).length;
  log.info(`merge: ${results.length} results from shards (alive=${aliveIn})`);

  const store = createStore();
  try {
    await store.applyResults(results);

    // ---- geo enrichment for freshly alive proxies ----
    const pool = await store.loadPool();
    const needGeo = [...pool.values()].filter((r) => r.alive && !r.country);
    const ipHosts = [...new Set(needGeo.map((r) => r.host))];
    let geoFilled = 0;
    if (ipHosts.length) {
      const geo = await geoLookup(ipHosts);
      const entries = needGeo.map((r) => ({
        key: r.key,
        country: geo.get(r.host)?.country ?? null,
        city: geo.get(r.host)?.city ?? null,
        asn: geo.get(r.host)?.asn ?? null,
        org: geo.get(r.host)?.org ?? null,
      }));
      await store.applyGeo(entries);
      geoFilled = entries.filter((e) => e.country).length;
    }

    const pruned = await store.prune({ keepMax: cfg.storeMaxRecords, deadAfterMs: cfg.deadAfterMs });

    // ---- next cycle's re-check queue ----
    const pending = await store.selectPending({
      limit: cfg.maxNewPerCycle,
      aliveAfterMs: cfg.aliveFreshMs,
      retryFailedAfterMs: cfg.retryFailedAfterHours * 3600_000,
      maxRecords: cfg.storeMaxRecords,
    });
    const pendingWriter = jsonlGzWriter<{ protocol: string; host: string; port: number; seenBy: string[] }>(
      poolStatePath(),
    );
    for (const rec of pending) {
      pendingWriter.write({ protocol: rec.protocol, host: rec.host, port: rec.port, seenBy: rec.seenBy });
    }
    await pendingWriter.close();

    // ---- publish ----
    const poolNow = [...pool.values()].filter((r) => (r.lastOk ?? 0) > Date.now() - cfg.publishFreshMs);
    // apply the /24 cap: a single network can dominate the pool
    const perSubnet = new Map<string, number>();
    const capped = poolNow.filter((r) => {
      const s = subnetOfHost(r.host);
      const n = (perSubnet.get(s) ?? 0) + 1;
      if (n > cfg.maxPerSubnet) return false;
      perSubnet.set(s, n);
      return true;
    });

    const generatedAt = Date.now();
    const report = renderAll(capped, {
      dataDir: cfg.dataDir,
      topN: cfg.topN,
      generatedAt,
      publishHistory: cfg.publishHistory,
    });

    const meta = {
      generatedAt,
      generatedIso: new Date(generatedAt).toISOString(),
      runId: cfg.runId,
      pipeline: 'fetch->validate(matrix)->merge->publish',
      store: store.kind(),
      counts: {
        poolSize: pool.size,
        freshPool: poolNow.length,
        afterSubnetCap: capped.length,
        published: report.total,
        pendingNextRun: pending.length,
        storeRecords: pool.size,
      },
      byProtocol: report.byProtocol,
    };
    atomicWriteJson(path.join(cfg.dataDir, 'meta.json'), meta);

    // ---- benchmark: what each public list is actually worth ----
    const perSourceAlive = new Map<string, { alive: number; latencies: number[]; grades: Record<string, number> }>();
    for (const r of results) {
      if (!r.alive) continue;
      for (const src of r.seenBy) {
        let a = perSourceAlive.get(src);
        if (!a) {
          a = { alive: 0, latencies: [], grades: {} };
          perSourceAlive.set(src, a);
        }
        a.alive++;
        if (r.latencyMs !== null) a.latencies.push(r.latencyMs);
        if (r.anonymity) a.grades[r.anonymity] = (a.grades[r.anonymity] ?? 0) + 1;
      }
    }
    let fetchReportForBench: {
      sources: Array<{ id: string; parsed: number; lastCommitDays: number | null }>;
      totalParsed: number;
      totalUnique: number;
      sampled: number;
    };
    try {
      fetchReportForBench = JSON.parse(fs.readFileSync(path.join(cfg.dataDir, 'fetch-report.json'), 'utf8'));
    } catch {
      // the fetch job uploads this artifact; without it the cycle counts are
      // unknown, the per-source rates still come from the sampled candidates
      log.warn('merge: fetch-report.json missing - cycle totals are zero this run');
      fetchReportForBench = { sources: [], totalParsed: 0, totalUnique: 0, sampled: 0 };
    }
    const aliveInput = results
      .filter((r) => r.alive)
      .map((r) => ({
        key: `${r.protocol}://${r.host}:${r.port}`,
        latency: r.latencyMs,
        grade: r.anonymity,
      }));
    // a source only gets credit for the keys it published itself; the
    // sampled candidate artefact (from the fetch job) is that universe
    const sourceKeys = new Map<string, string[]>();
    try {
      for (const c of readCandidates()) {
        for (const src of c.seenBy) {
          const list = sourceKeys.get(src);
          if (list) list.push(`${c.protocol}://${c.host}:${c.port}`);
          else sourceKeys.set(src, [`${c.protocol}://${c.host}:${c.port}`]);
        }
      }
    } catch {
      /* no candidate artefact: falls back to source-agnostic credit */
    }
    const benchmark = buildBenchmark(
      generatedAt,
      {
        parsed: fetchReportForBench.totalParsed,
        unique: fetchReportForBench.totalUnique,
        sampled: fetchReportForBench.sampled,
        alive: aliveInput.length,
      },
      fetchReportForBench.sources.map((s) => ({
        id: s.id,
        // the denominator is only what this pipeline actually checked; the
        // full published count rides along as context
        candidates: sourceKeys.get(s.id)?.length ?? 0,
        published: s.parsed,
        staleDays: s.lastCommitDays ?? null,
        keys: sourceKeys.get(s.id),
      })),
      aliveInput,
    );
    atomicWriteJson(path.join(cfg.dataDir, 'benchmark.json'), benchmark);

    // rank history: "who moved up since last cycle"
    const historyFile = path.join(cfg.dataDir, 'source-history.json');
    let sourceHistory: HistoryPoint[] = [];
    try {
      const parsed = JSON.parse(fs.readFileSync(historyFile, 'utf8'));
      if (Array.isArray(parsed)) sourceHistory = parsed;
    } catch {
      /* first run */
    }
    sourceHistory = appendHistory(sourceHistory, benchmark);
    atomicWriteJson(historyFile, sourceHistory);

    // ---- history: the pool's recent life, published for status consumers ----
    const HISTORY_MAX = 96;
    const poolHistoryFile = path.join(cfg.dataDir, 'history.json');
    let history: CycleStats[] = [];
    try {
      const prev = JSON.parse(fs.readFileSync(poolHistoryFile, 'utf8'));
      if (Array.isArray(prev)) history = prev;
    } catch {
      /* first run */
    }
    const poolForStats = capped;
    const eliteCount = poolForStats.filter((p) => p.anonymity === 'elite').length;
    const cycleStats: CycleStats = {
      ts: generatedAt,
      total: report.total,
      // the real country count, not the length of the top list: the hero
      // shows every country, so history must not claim a different number
      countries: new Set(capped.map((p) => p.country).filter(Boolean)).size,
      http: report.byProtocol.http ?? 0,
      socks4: report.byProtocol.socks4 ?? 0,
      socks5: report.byProtocol.socks5 ?? 0,
      medianLatency: report.total > 0 ? medianLatencyOf(capped) : null,
      eliteRate: poolForStats.length ? eliteCount / poolForStats.length : null,
      mitm: poolForStats.filter((p) => p.tlsMitm).length,
      countriesTop: topCountriesOf(capped, 8),
    };
    history.push(cycleStats);
    history = history.slice(-HISTORY_MAX);
    atomicWriteJson(poolHistoryFile, history);

    const fetchReportPath = path.join(cfg.dataDir, 'fetch-report.json');
    const parsedBySource: Record<string, number> = {};
    try {
      const fr = JSON.parse(fs.readFileSync(fetchReportPath, 'utf8')) as {
        sources?: Array<{ id: string; parsed: number }>;
      };
      for (const src of fr.sources ?? []) parsedBySource[src.id] = src.parsed;
    } catch {
      /* first run or a missing fetch report: provenance lives in the log only */
    }

    const aliveBySource: Record<string, number> = {};
    for (const r of results) {
      if (!r.alive) continue;
      for (const src of r.seenBy) {
        aliveBySource[src] = (aliveBySource[src] ?? 0) + 1;
      }
    }

    const mergeReport: MergeReport = {
      startedAt,
      finishedAt: Date.now(),
      shards: cfg.shardCount,
      resultsIn: results.length,
      aliveIn,
      poolSize: pool.size,
      published: report.total,
      byProtocol: report.byProtocol,
      pendingForNextRun: pending.length,
      geoFilled,
      pruned,
      maxPerSubnet: cfg.maxPerSubnet,
      aliveBySource,
      parsedBySource,
    };
    atomicWriteJson(path.join(cfg.dataDir, 'merge-report.json'), mergeReport);

    await store.flush();
    log.info(
      `merge: published=${report.total} pool=${pool.size} pendingNext=${pending.length} geo+${geoFilled} pruned=${pruned}`,
    );

    if (cfg.healthcheckUrl) {
      try {
        await fetch(cfg.healthcheckUrl);
        log.info('merge: healthcheck pinged');
      } catch (e) {
        log.warn(`merge: healthcheck failed: ${(e as Error).message}`);
      }
    }
    return mergeReport;
  } finally {
    await store.close();
  }
}
