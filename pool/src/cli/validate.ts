import path from 'node:path';
import { config } from '../config.js';
import { log } from '../log.js';
import { readJsonlGz, jsonlGzWriter, atomicWriteJson } from '../io/jsonl.js';
import { readCandidates } from './fetch.js';
import { checkAll } from '../check/runner.js';
import { shardOf } from '../normalize/index.js';
import { defaultTargets } from '../check/targets.js';
import type { ProxyTarget } from '../check/proxy-client.js';
import type { CheckResultRecord } from '../store/types.js';
import type { Candidate } from '../sources/types.js';

export interface ValidateReport {
  shardIndex: number;
  shardCount: number;
  poolFromPreviousRun: number;
  candidatesThisRun: number;
  checked: number;
  alive: number;
  elapsedMs: number;
  startedAt: number;
  finishedAt: number;
}

export function resultsPath(shardIndex: number): string {
  return path.join(config().workDir, `results-${shardIndex}.jsonl.gz`);
}

/** Written by merge, read by the next cycle's validate jobs (cache-carried). */
export function poolStatePath(): string {
  return path.join(config().stateDir, 'pool-state.jsonl.gz');
}

/**
 * Command: validate one shard of (previous pool + this cycle's candidates).
 * Checking from GitHub-hosted runner IPs keeps the operator's own
 * infrastructure out of the proxy-owner logs entirely.
 */
export async function cmdValidate(): Promise<ValidateReport> {
  const cfg = config();
  const startedAt = Date.now();

  const poolPrevious = readJsonlGz<Candidate>(poolStatePath());
  const candidates = readCandidates();

  const targets: Array<ProxyTarget & { seenBy: string[] }> = [];
  const seen = new Set<string>();
  const add = (e: Candidate & { seenBy?: string[] }) => {
    const k = `${e.protocol}:${e.host}:${e.port}`;
    if (seen.has(k)) return;
    seen.add(k);
    targets.push({
      protocol: e.protocol === 'https' ? 'http' : e.protocol,
      host: e.host,
      port: e.port,
      user: e.user,
      pass: e.pass,
      seenBy: e.seenBy ?? [k],
    });
  };

  for (const e of poolPrevious) {
    if (shardOf(`${e.protocol}:${e.host}:${e.port}`, cfg.shardCount) !== cfg.shardIndex) continue;
    add(e);
  }
  for (const e of candidates) {
    if (shardOf(`${e.protocol}:${e.host}:${e.port}`, cfg.shardCount) !== cfg.shardIndex) continue;
    add(e);
  }

  log.info(
    `validate: shard ${cfg.shardIndex}/${cfg.shardCount}: ${poolPrevious.length} pool + ${candidates.length} candidates -> ${targets.length} targets`,
  );

  const outFile = resultsPath(cfg.shardIndex);
  const writer = jsonlGzWriter<CheckResultRecord>(outFile);
  const { stats } = await checkAll(
    targets,
    {
      concurrency: cfg.checkConcurrency,
      timeoutMs: cfg.checkTimeoutMs,
      stage1TimeoutMs: cfg.stage1TimeoutMs,
      targets: defaultTargets(),
    },
    (rec) => writer.write(rec),
  );
  await writer.close();

  const report: ValidateReport = {
    shardIndex: cfg.shardIndex,
    shardCount: cfg.shardCount,
    poolFromPreviousRun: poolPrevious.length,
    candidatesThisRun: candidates.length,
    checked: stats.checked,
    alive: stats.alive,
    elapsedMs: stats.elapsedMs,
    startedAt,
    finishedAt: Date.now(),
  };
  atomicWriteJson(path.join(config().workDir, `validate-report-${cfg.shardIndex}.json`), report);
  log.info(
    `validate: shard ${cfg.shardIndex}: checked=${stats.checked} alive=${stats.alive} in ${(stats.elapsedMs / 1000).toFixed(1)}s -> ${outFile}`,
  );
  return report;
}
