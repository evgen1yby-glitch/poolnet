import type { Anonymity } from '../check/stage.js';

export interface CheckResultRecord {
  protocol: string;
  host: string;
  port: number;
  user?: string;
  pass?: string;
  alive: boolean;
  latencyMs: number | null;
  remoteIp: string | null;
  anonymity: Anonymity | 'unknown';
  tlsIssuer: string | null;
  tlsMitm: boolean;
  supportsTls: boolean;
  error: string | null;
  checkedAt: number;
  /** provenance: source ids this candidate was reported by in the cycle */
  seenBy: string[];
}

export interface ProxyRecord extends CheckResultRecord {
  key: string;
  firstSeen: number;
  lastOk: number | null;
  lastCheck: number;
  checks: number;
  okChecks: number;
  fails: number;
  country: string | null;
  city: string | null;
  asn: number | null;
  org: string | null;
  uptime1h: [number, number];
  uptime24h: [number, number];
  uptime7d: [number, number];
  uptime30d: [number, number];
  latencySamples: number[];
  disabledUntil: number | null;
}

export interface Store {
  /** All records that were alive recently or were checked recently. */
  loadPool(): Promise<Map<string, ProxyRecord>>;
  /** Apply check outcomes, updating rolling counters. */
  applyResults(results: CheckResultRecord[]): Promise<void>;
  /** Attach geo enrichment (country/city/asn/org) to existing records. */
  applyGeo(entries: GeoEntry[]): Promise<void>;
  /** Records to re-check first: past-due alive proxies, then recent failures. */
  selectPending(opts: {
    limit: number;
    aliveAfterMs: number;
    retryFailedAfterMs: number;
    maxRecords: number;
  }): Promise<ProxyRecord[]>;
  /** Drop noise: keep the store bounded. */
  prune(opts: { keepMax: number; deadAfterMs: number }): Promise<number>;
  /** Persist state (no-op for servers that persist per call). */
  flush(): Promise<void>;
  close(): Promise<void>;
  kind(): 'fs' | 'postgres';
}

export interface GeoEntry {
  key: string;
  country: string | null;
  city: string | null;
  asn: number | null;
  org: string | null;
}

export function recordKey(protocol: string, host: string, port: number): string {
  return `${protocol}://${host}:${port}`;
}

export function subnetOfHost(host: string): string {
  const parts = host.split('.');
  return parts.length === 4 ? parts.slice(0, 3).join('.') : host;
}

const HOUR = 3600_000;

/**
 * Merge a rolling [total, ok] window with decay. The decay is the age of the
 * previous sample against the window, so the same check sequence always
 * produces the same uptime no matter when in the hour it runs.
 */
export function rollWindow(prev: [number, number], ok: boolean, ageMs: number, windowMs: number): [number, number] {
  const factor = Math.exp(-Math.max(0, ageMs) / windowMs);
  const total = prev[0] * factor;
  const good = prev[1] * factor;
  return [total + 1, good + (ok ? 1 : 0)];
}

export function uptimePct(w: [number, number] | undefined): number | null {
  if (!w || w[0] === 0) return null;
  return Math.round((w[1] / w[0]) * 1000) / 10;
}

export function percentile(samples: number[], p: number): number | null {
  if (samples.length === 0) return null;
  const s = [...samples].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1));
  return Math.round(s[idx]!);
}

export function mergeLatency(prev: number[], next: number | null, max = 32): number[] {
  if (next === null) return prev.slice(-max);
  return [...prev, next].slice(-max);
}

export function newRecord(r: CheckResultRecord): ProxyRecord {
  const now = r.checkedAt;
  return {
    ...r,
    key: recordKey(r.protocol, r.host, r.port),
    firstSeen: now,
    lastOk: r.alive ? now : null,
    lastCheck: now,
    checks: 1,
    okChecks: r.alive ? 1 : 0,
    fails: r.alive ? 0 : 1,
    country: null,
    city: null,
    asn: null,
    org: null,
    uptime1h: [1, r.alive ? 1 : 0],
    uptime24h: [1, r.alive ? 1 : 0],
    uptime7d: [1, r.alive ? 1 : 0],
    uptime30d: [1, r.alive ? 1 : 0],
    latencySamples: r.latencyMs !== null ? [r.latencyMs] : [],
    disabledUntil: null,
  };
}

export function applyResult(rec: ProxyRecord, r: CheckResultRecord): ProxyRecord {
  const now = r.checkedAt;
  const ageMs = now - rec.lastCheck;
  const lat = mergeLatency(rec.latencySamples, r.latencyMs);
  const merged: ProxyRecord = {
    ...rec,
    alive: r.alive,
    lastCheck: now,
    checks: rec.checks + 1,
    okChecks: rec.okChecks + (r.alive ? 1 : 0),
    fails: r.alive ? 0 : rec.fails + 1,
    // a dead check ends the freshness window: the record is not alive now,
    // so publishing it as fresh would be a lie
    lastOk: r.alive ? now : null,
    latencyMs: r.latencyMs ?? rec.latencyMs,
    // Only this check's exit evidence counts. Carrying the previous address
    // forward would keep a false "exits here" claim after a target that does
    // not report one, and the publication guard would never see it.
    remoteIp: r.remoteIp,
    // a new check is the only evidence we accept: if this run could not grade
    // anonymity, the previous grade (often a false "elite") must not survive
    anonymity: r.anonymity,
    tlsIssuer: r.tlsIssuer ?? rec.tlsIssuer,
    tlsMitm: r.tlsMitm || rec.tlsMitm,
    supportsTls: r.supportsTls || rec.supportsTls,
    error: r.error,
    seenBy: Array.from(new Set([...rec.seenBy, ...r.seenBy])),
    latencySamples: lat,
    uptime1h: rollWindow(rec.uptime1h, r.alive, ageMs, HOUR),
    uptime24h: rollWindow(rec.uptime24h, r.alive, ageMs, 24 * HOUR),
    uptime7d: rollWindow(rec.uptime7d, r.alive, ageMs, 7 * 24 * HOUR),
    uptime30d: rollWindow(rec.uptime30d, r.alive, ageMs, 30 * 24 * HOUR),
  };
  return merged;
}
