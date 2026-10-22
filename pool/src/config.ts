import { parseArgs } from 'node:util';
import fs from 'node:fs';
import path from 'node:path';

export const REPO_ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');

function int(v: string | undefined, dflt: number): number {
  if (!v) return dflt;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : dflt;
}

function bool(v: string | undefined, dflt: boolean): boolean {
  if (!v) return dflt;
  return /^(1|true|yes|on)$/i.test(v);
}

function list(v: string | undefined, dflt: string[]): string[] {
  if (!v) return dflt;
  return v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

export type StoreKind = 'fs' | 'postgres';

export interface Config {
  sourcesFile: string;
  dataDir: string;
  stateDir: string;
  workDir: string;
  store: StoreKind;
  databaseUrl: string | null;

  // fetching
  fetchTimeoutMs: number;
  fetchUserAgent: string;
  perSourceMin: number;
  disabledSources: string[];

  // checking
  checkConcurrency: number;
  checkTimeoutMs: number;
  stage1TimeoutMs: number;
  checkTargets: string[];
  maxPerSubnet: number;
  retryFailedAfterHours: number;
  maxNewPerCycle: number;

  // sharding (GitHub Actions matrix)
  shardIndex: number;
  shardCount: number;

  // geo
  geoipMmdbPath: string | null;
  geoipProvider: 'mmdb' | 'ipapi' | 'auto' | 'none';

  // publish
  topN: number;
  publishHistory: boolean;
  publishFreshMs: number;
  aliveFreshMs: number;
  storeMaxRecords: number;
  deadAfterMs: number;
  healthcheckUrl: string | null;
  runId: string | null;
}

let cached: Config | null = null;

export function config(): Config {
  if (cached) return cached;
  const {
    OPP_SOURCES_FILE,
    OPP_DATA_DIR,
    OPP_STATE_DIR,
    OPP_WORK_DIR,
    OPP_STORE,
    DATABASE_URL,
    OPP_FETCH_TIMEOUT_MS,
    OPP_FETCH_USER_AGENT,
    OPP_PER_SOURCE_MIN,
    OPP_DISABLED_SOURCES,
    OPP_CONCURRENCY,
    OPP_CHECK_TIMEOUT_MS,
    OPP_STAGE1_TIMEOUT_MS,
    OPP_CHECK_TARGETS,
    OPP_MAX_PER_SUBNET,
    OPP_RETRY_FAILED_AFTER_HOURS,
    OPP_MAX_NEW_PER_CYCLE,
    SHARD_INDEX,
    SHARD_COUNT,
    OPP_GEOIP_MMDB,
    OPP_GEOIP_PROVIDER,
    OPP_TOP_N,
    OPP_PUBLISH_HISTORY,
    OPP_PUBLISH_FRESH_MS,
    OPP_ALIVE_FRESH_MS,
    OPP_STORE_MAX_RECORDS,
    OPP_DEAD_AFTER_MS,
    HEALTHCHECK_URL,
  } = process.env;

  const envMmdb = OPP_GEOIP_MMDB && fs.existsSync(OPP_GEOIP_MMDB) ? OPP_GEOIP_MMDB : null;
  const provider = (OPP_GEOIP_PROVIDER as Config['geoipProvider']) || (envMmdb ? 'mmdb' : 'auto');

  cached = {
    sourcesFile: OPP_SOURCES_FILE || path.join(REPO_ROOT, 'sources.yaml'),
    dataDir: OPP_DATA_DIR || path.join(REPO_ROOT, 'data'),
    stateDir: OPP_STATE_DIR || path.join(REPO_ROOT, '.state'),
    workDir: OPP_WORK_DIR || path.join(REPO_ROOT, '.work'),
    store: (OPP_STORE as StoreKind) || 'fs',
    databaseUrl: DATABASE_URL || null,

    fetchTimeoutMs: int(OPP_FETCH_TIMEOUT_MS, 60_000),
    perSourceMin: int(OPP_PER_SOURCE_MIN, 120),
    fetchUserAgent:
      OPP_FETCH_USER_AGENT || 'Mozilla/5.0 (compatible; open-proxy-pool/0.1; +https://github.com/open-proxy-pool)',
    disabledSources: list(OPP_DISABLED_SOURCES, []),

    checkConcurrency: int(OPP_CONCURRENCY, 400),
    checkTimeoutMs: int(OPP_CHECK_TIMEOUT_MS, 12_000),
    stage1TimeoutMs: int(OPP_STAGE1_TIMEOUT_MS, 5_000),
    // Liveness targets are plain and permissive; JSON echoes carry the
    // headers that grade anonymity. Both lists rotate under load.
    checkTargets: list(OPP_CHECK_TARGETS, [
      'https://api.ipify.org/',
      'https://1.1.1.1/',
      'https://ipinfo.io/ip',
      'https://ifconfig.me/ip',
      'https://icanhazip.com',
      'https://ident.me',
      'https://httpbingo.org/get',
      'https://postman-echo.com/get',
    ]),
    maxPerSubnet: int(OPP_MAX_PER_SUBNET, 512),
    retryFailedAfterHours: int(OPP_RETRY_FAILED_AFTER_HOURS, 12),
    maxNewPerCycle: int(OPP_MAX_NEW_PER_CYCLE, 120_000),

    shardIndex: int(SHARD_INDEX, 0),
    shardCount: int(SHARD_COUNT, 1),

    geoipMmdbPath: envMmdb,
    geoipProvider: provider,

    topN: int(OPP_TOP_N, 1000),
    publishHistory: bool(OPP_PUBLISH_HISTORY, false),
    publishFreshMs: int(OPP_PUBLISH_FRESH_MS, 4 * 3600_000),
    aliveFreshMs: int(OPP_ALIVE_FRESH_MS, 20 * 60_000),
    storeMaxRecords: int(OPP_STORE_MAX_RECORDS, 400_000),
    deadAfterMs: int(OPP_DEAD_AFTER_MS, 7 * 24 * 3600_000),
    healthcheckUrl: HEALTHCHECK_URL || null,
    runId: process.env.GITHUB_RUN_ID ?? null,
  };
  return cached;
}

/** Reset cached config (tests only). */
export function resetConfig(): void {
  cached = null;
}

export function cliArgs() {
  return parseArgs({
    options: {
      cycles: { type: 'string', short: 'c' },
      limit: { type: 'string', short: 'l' },
      json: { type: 'boolean', short: 'j' },
      help: { type: 'boolean', short: 'h' },
    },
    allowPositionals: true,
  });
}

export function ensureDir(p: string): string {
  fs.mkdirSync(p, { recursive: true });
  return p;
}
