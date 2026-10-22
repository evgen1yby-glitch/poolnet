#!/usr/bin/env node
/**
 * Builds the website's data bundle from the pipeline output:
 *   site/data/meta.json     — stats, countries, sources, run info
 *   site/data/proxies.json  — the pool, one entry per verified proxy
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataDir = path.join(root, 'data');
const outDir = path.join(root, 'site', 'data');

const read = (f) => JSON.parse(fs.readFileSync(path.join(dataDir, f), 'utf8'));

// the pool's recent life: one point per published cycle (absent on a fresh run)
let history = [];
try {
  const parsed = JSON.parse(fs.readFileSync(path.join(dataDir, 'history.json'), 'utf8'));
  if (Array.isArray(parsed)) history = parsed;
} catch {
  /* no history yet */
}

const benchmark = read('benchmark.json');
let sourceHistory = [];
try {
  const parsedH = JSON.parse(fs.readFileSync(path.join(dataDir, 'source-history.json'), 'utf8'));
  if (Array.isArray(parsedH)) sourceHistory = parsedH;
} catch {
  /* no benchmark history yet */
}

const proxies = read('proxies.json');
const stats = read('stats.json');
const meta = read('meta.json');
const fetchReport = read('fetch-report.json');
const mergeReport = read('merge-report.json');

const MAX = 20000;

const pool = proxies.proxies.slice(0, MAX).map((p) => ({
  id: `${p.host}:${p.port}`,
  host: p.host,
  port: p.port,
  protocol: p.protocol,
  grade: p.anonymity,
  latency: p.latency_ms,
  uptime1h: p.uptime_1h,
  uptime24h: p.uptime_24h,
  uptime7d: p.uptime_7d,
  uptime30d: p.uptime_30d,
  country: p.country,
  exitIp: p.exit_ip,
  mitm: p.tls_mitm,
  lastOk: p.last_ok,
  sources: p.sources,
}));

const metaOut = {
  generatedIso: meta.generatedIso ?? new Date().toISOString(),
  poolTruncated: proxies.proxies.length > MAX,
  poolTotal: proxies.proxies.length,
  runId: meta.runId ?? null,
  total: stats.total,
  byProtocol: stats.byProtocol,
  anonymity: stats.anonymity,
  medianLatencyMs: stats.medianLatencyMs,
  p95LatencyMs: stats.p95LatencyMs,
  countries: stats.countries.map((c) => ({ cc: c.country, n: c.count })),
  sourcesOk: fetchReport.sources.filter((s) => s.ok).length,
  sourcesTotal: fetchReport.sources.length,
  sources: fetchReport.sources
    .map((s) => ({ id: s.id, parsed: s.parsed, alive: mergeReport.aliveBySource?.[s.id] ?? 0 }))
    .sort((a, b) => b.alive - a.alive)
    .slice(0, 20),
  fingerprint: {
    parsed: fetchReport.totalParsed,
    unique: fetchReport.totalUnique,
    sampled: fetchReport.sampled,
  },
  // the pool's recent life: one point per published cycle
  history: history.map((h) => ({
    ts: h.ts,
    total: h.total,
    http: h.http,
    socks4: h.socks4,
    socks5: h.socks5,
    medianLatency: h.medianLatency ?? null,
    eliteRate: h.eliteRate ?? null,
    mitm: h.mitm ?? 0,
    countries: h.countries ?? null,
    countriesTop: h.countriesTop ?? [],
  })),
  benchmark: {
    generatedAt: benchmark.generatedAt,
    generatedIso: new Date(benchmark.generatedAt).toISOString(),
    cycle: benchmark.cycle,
    sources: benchmark.sources,
    ranks: benchmark.ranks,
  },
  // rank + live-rate movement between cycles: the leaderboard's memory
  sourceHistory: sourceHistory.slice(-96).map((h) => ({ ts: h.ts, ranks: h.ranks, live: h.live })),
};

fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'meta.json'), JSON.stringify(metaOut));
fs.writeFileSync(path.join(outDir, 'proxies.json'), JSON.stringify(pool));
console.log(
  `web data: ${pool.length} proxies, ${metaOut.countries.length} countries, ${history.length} history points, ` +
    `${benchmark.sources.length} benchmarked sources, generated ${metaOut.generatedIso}`,
);
