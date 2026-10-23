import fs from 'node:fs';
import path from 'node:path';
import { percentile, uptimePct, type ProxyRecord } from '../store/types.js';

export interface PublishedProxy {
  protocol: string;
  host: string;
  port: number;
  user?: string;
  pass?: string;
  latencyMs: number | null;
  anonymity: string;
  exitIp: string | null;
  country: string | null;
  uptime1h: number | null;
  uptime24h: number | null;
  uptime7d: number | null;
  uptime30d: number | null;
  mitm: boolean;
  supportsTls: boolean;
  lastOk: number;
  sources: number;
}

export function toPublished(rec: ProxyRecord): PublishedProxy {
  return {
    protocol: rec.protocol,
    host: rec.host,
    port: rec.port,
    user: rec.user,
    pass: rec.pass,
    latencyMs: rec.latencyMs,
    anonymity: rec.anonymity,
    exitIp: rec.remoteIp,
    country: rec.country,
    uptime1h: uptimePct(rec.uptime1h),
    uptime24h: uptimePct(rec.uptime24h),
    uptime7d: uptimePct(rec.uptime7d),
    uptime30d: uptimePct(rec.uptime30d),
    mitm: rec.tlsMitm,
    supportsTls: rec.supportsTls,
    lastOk: rec.lastOk ?? rec.lastCheck,
    sources: rec.seenBy.length,
  };
}

const ANON_RANK: Record<string, number> = { elite: 0, anonymous: 1, transparent: 2, unknown: 3 };

/** Quality order: safer anonymity, no TLS MITM, lower latency, more sources. */
export function qualitySort(a: PublishedProxy, b: PublishedProxy): number {
  const an = (ANON_RANK[a.anonymity] ?? 3) - (ANON_RANK[b.anonymity] ?? 3);
  if (an !== 0) return an;
  const mi = Number(a.mitm) - Number(b.mitm);
  if (mi !== 0) return mi;
  const la = (a.latencyMs ?? 999_999) - (b.latencyMs ?? 999_999);
  if (la !== 0) return la;
  return b.sources - a.sources;
}

export function lineFor(p: PublishedProxy): string {
  const auth = p.user ? `${p.user}:${p.pass ?? ''}@` : '';
  return `${p.protocol}://${auth}${p.host}:${p.port}`;
}

export function plainLineFor(p: PublishedProxy): string {
  const auth = p.user ? `${p.user}:${p.pass ?? ''}@` : '';
  return `${auth}${p.host}:${p.port}`;
}

export interface RenderOptions {
  dataDir: string;
  topN: number;
  generatedAt: number;
  publishHistory: boolean;
}

export interface RenderReport {
  total: number;
  byProtocol: Record<string, number>;
  files: string[];
}

export function renderAll(records: ProxyRecord[], opts: RenderOptions): RenderReport {
  const dir = path.join(opts.dataDir);
  fs.mkdirSync(dir, { recursive: true });
  fs.mkdirSync(path.join(dir, 'country'), { recursive: true });

  const pool = records
    .filter((r) => r.lastOk !== null && r.lastOk > 0)
    .map(toPublished)
    .sort(qualitySort);

  const files: string[] = [];
  const write = (rel: string, content: string) => {
    fs.writeFileSync(path.join(dir, rel), content);
    files.push(rel);
  };

  write('all.txt', pool.map(lineFor).join('\n') + '\n');

  const byProtocol: Record<string, number> = {};
  for (const p of pool) {
    byProtocol[p.protocol] = (byProtocol[p.protocol] ?? 0) + 1;
  }
  for (const proto of ['http', 'socks4', 'socks5']) {
    const list = pool.filter((p) => p.protocol === proto);
    write(`${proto}.txt`, list.map(lineFor).join('\n') + '\n');
  }

  write(`top${opts.topN}.txt`, pool.slice(0, opts.topN).map(lineFor).join('\n') + '\n');
  write('top100.txt', pool.slice(0, 100).map(plainLineFor).join('\n') + '\n');

  // JSON carries full metadata; stripped fields keep the export lean.
  write(
    'proxies.json',
    JSON.stringify(
      {
        generatedAt: opts.generatedAt,
        count: pool.length,
        proxies: pool.map((p) => ({
          protocol: p.protocol,
          host: p.host,
          port: p.port,
          user: p.user,
          password: p.pass,
          latency_ms: p.latencyMs,
          anonymity: p.anonymity,
          exit_ip: p.exitIp,
          country: p.country,
          uptime_1h: p.uptime1h,
          uptime_24h: p.uptime24h,
          uptime_7d: p.uptime7d,
          uptime_30d: p.uptime30d,
          tls_mitm: p.mitm,
          last_ok: p.lastOk,
          sources: p.sources,
        })),
      },
      null,
      2,
    ),
  );

  // country shards: every country with a handful of entries, largest first,
  // so consumers can address small markets as well as the big ones
  const byCountry = new Map<string, PublishedProxy[]>();
  for (const p of pool) {
    if (!p.country) continue;
    const arr = byCountry.get(p.country) ?? [];
    arr.push(p);
    byCountry.set(p.country, arr);
  }
  const writtenCountries = new Set<string>();
  for (const [cc, list] of [...byCountry.entries()].sort((a, b) => b[1].length - a[1].length)) {
    if (list.length < 5) continue;
    write(`country/${cc}.txt`, list.map(lineFor).join('\n') + '\n');
    writtenCountries.add(`${cc}.txt`);
  }
  // A country that drops below the shard threshold stops being rewritten, and
  // its previous file would otherwise stay downloadable forever with proxies
  // that are no longer published. The export must describe one generation.
  for (const name of fs.readdirSync(path.join(dir, 'country'))) {
    if (name.endsWith('.txt') && !writtenCountries.has(name)) {
      fs.rmSync(path.join(dir, 'country', name));
    }
  }

  const stats = {
    generatedAt: opts.generatedAt,
    generatedIso: new Date(opts.generatedAt).toISOString(),
    total: pool.length,
    byProtocol,
    medianLatencyMs: percentile(
      pool.filter((p) => p.latencyMs !== null).map((p) => p.latencyMs!),
      50,
    ),
    p95LatencyMs: percentile(
      pool.filter((p) => p.latencyMs !== null).map((p) => p.latencyMs!),
      95,
    ),
    countries: [...byCountry.entries()]
      .map(([cc, list]) => ({ country: cc, count: list.length }))
      .sort((a, b) => b.count - a.count),
    anonymity: pool.reduce<Record<string, number>>((acc, p) => {
      const k = p.anonymity ?? 'unknown';
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {}),
    mitm: pool.filter((p) => p.mitm).length,
    tlsCapable: pool.filter((p) => p.supportsTls).length,
  };
  write('stats.json', JSON.stringify(stats, null, 2) + '\n');

  // shields.io dynamic endpoint payloads (consumed via jsDelivr)
  const badgeDir = path.join(dir, 'badges');
  fs.mkdirSync(badgeDir, { recursive: true });
  const badge = (name: string, label: string, message: string, color: string) => {
    fs.writeFileSync(
      path.join(badgeDir, `${name}.json`),
      JSON.stringify({ schemaVersion: 1, label, message, color }, null, 2),
    );
    files.push(`badges/${name}.json`);
  };
  badge('alive', 'proxies alive', String(pool.length), 'brightgreen');
  badge('total', 'proxies total', String(pool.length), 'blue');
  badge('http', 'http', String(byProtocol.http ?? 0), 'blue');
  badge('socks4', 'socks4', String(byProtocol.socks4 ?? 0), 'blue');
  badge('socks5', 'socks5', String(byProtocol.socks5 ?? 0), 'blue');
  badge(
    'updated',
    'last update',
    new Date(opts.generatedAt).toISOString().slice(0, 16).replace('T', ' '),
    'informational',
  );

  return { total: pool.length, byProtocol, files };
}
