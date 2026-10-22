import { config, resetConfig } from '../config.js';
import { cmdFetch } from './fetch.js';
import { cmdValidate } from './validate.js';
import { cmdMerge } from './merge.js';
import fs from 'node:fs';
import path from 'node:path';
import { atomicWriteJson } from '../io/jsonl.js';

/**
 * Command: full pipeline in one process (local development and self-hosted
 * runs). The GitHub workflow splits these into fetch -> matrix validate ->
 * merge steps; the semantics are identical.
 */
export async function cmdCycle(): Promise<{ fetch: unknown; validate: unknown; merge: unknown }> {
  const cfg = config();
  fs.mkdirSync(cfg.workDir, { recursive: true });
  fs.mkdirSync(cfg.stateDir, { recursive: true });

  // clean stale shard results: a local cycle must only merge its own
  for (const f of fs.readdirSync(cfg.workDir).filter((f) => /^results-\d+\.jsonl\.gz$/.test(f))) {
    fs.rmSync(path.join(cfg.workDir, f));
  }

  const fetchReport = await cmdFetch();
  const shardCount = cfg.shardCount;
  const validateReports = [];
  for (let i = 0; i < shardCount; i++) {
    process.env.SHARD_INDEX = String(i);
    resetConfig();
    validateReports.push(await cmdValidate());
  }
  const mergeReport = await cmdMerge();
  atomicWriteJson(path.join(cfg.dataDir, 'cycle-report.json'), { fetchReport, validateReports, mergeReport });
  return { fetch: fetchReport, validate: validateReports, merge: mergeReport };
}
