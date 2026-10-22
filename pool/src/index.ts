#!/usr/bin/env node
import { resetConfig } from './config.js';
import { setDebug, log } from './log.js';
import { cmdFetch } from './cli/fetch.js';
import { cmdValidate } from './cli/validate.js';
import { cmdMerge } from './cli/merge.js';
import { cmdCycle } from './cli/cycle.js';
import { cmdDiscover } from './cli/discover.js';

const USAGE = `open-proxy-pool (opp)

Usage:
  opp fetch        download all sources, parse, dedupe, sample -> candidates.jsonl.gz
  opp validate     check one shard of the queue -> results-<shard>.jsonl.gz
  opp merge        merge shard results, enrich, render data/*
  opp publish      re-render data/ from the stored pool (no new checks)
  opp cycle        fetch + validate + merge in one process
  opp check <id|url>  fetch one source and measure its real live rate
  opp serve        run the distributed-mode coordinator (jobs + results over HTTP)
  opp node         contribute check capacity to a coordinator (distributed mode)
  opp roast        publish the weekly digest of the benchmark
  opp discover     probe GitHub for new candidate sources

Environment (all optional):
  OPP_SOURCES_FILE, OPP_DATA_DIR, OPP_STATE_DIR, OPP_WORK_DIR
  OPP_STORE=fs|postgres, DATABASE_URL
  OPP_CONCURRENCY, OPP_CHECK_TIMEOUT_MS, OPP_STAGE1_TIMEOUT_MS
  OPP_PER_SOURCE_MIN, OPP_MAX_NEW_PER_CYCLE, OPP_MAX_PER_SUBNET
  SHARD_INDEX, SHARD_COUNT (matrix mode)
  OPP_GEOIP_MMDB, OPP_GEOIP_PROVIDER=mmdb|ipapi|none
  OPP_TOP_N, OPP_PUBLISH_FRESH_MS, OPP_ALIVE_FRESH_MS
  HEALTHCHECK_URL
`;

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const command = args[0];
  if (!command || command === 'help' || command === '--help' || command === '-h') {
    process.stdout.write(USAGE);
    return;
  }
  if (process.env.DEBUG) setDebug(true);
  resetConfig();

  switch (command) {
    case 'fetch':
      await cmdFetch();
      break;
    case 'validate':
      await cmdValidate();
      break;
    case 'merge':
      await cmdMerge();
      break;
    case 'publish': {
      const { cmdPublish } = await import('./cli/publish.js');
      await cmdPublish();
      break;
    }
    case 'cycle':
      await cmdCycle();
      break;
    case 'check': {
      const target = process.argv[3];
      if (!target) {
        log.error('usage: opp check <source-id|url> — fetch one source and measure its real live rate');
        process.exitCode = 1;
        return;
      }
      const { cmdCheckSource } = await import('./cli/check-source.js');
      await cmdCheckSource(target);
      break;
    }
    case 'node': {
      const { runNode } = await import('./distributed/index.js');
      const url = process.env.COORDINATOR_URL;
      if (!url) {
        log.error('node mode needs COORDINATOR_URL (the coordinator /jobs endpoint base)');
        process.exitCode = 1;
        return;
      }
      const done = await runNode({
        coordinatorUrl: url,
        nodeId: process.env.NODE_ID || `node-${Math.random().toString(36).slice(2, 8)}`,
        token: process.env.NODE_TOKEN,
        once: process.env.NODE_ONCE === '1',
      });
      log.info(`node: checked ${done} candidates`);
      break;
    }
    case 'serve': {
      const { cmdServe } = await import('./cli/serve.js');
      await cmdServe({ token: process.env.OPP_SERVE_TOKEN });
      break;
    }
    case 'roast': {
      const { cmdRoast } = await import('./cli/roast.js');
      await cmdRoast();
      break;
    }
    case 'discover':
      await cmdDiscover();
      break;
    default:
      log.error(`unknown command: ${command}`);
      process.stdout.write(USAGE);
      process.exitCode = 1;
  }
}

main().catch((e) => {
  log.error(`fatal: ${(e as Error).stack ?? String(e)}`);
  process.exit(1);
});
