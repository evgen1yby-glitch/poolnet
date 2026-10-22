import { Pool } from 'pg';
import { log } from '../log.js';
import { applyResult, newRecord, recordKey, type CheckResultRecord, type ProxyRecord, type Store } from './types.js';

/**
 * Postgres-backed store for projects that want long-lived statistics
 * (uptime windows, history) across pipeline runs without the snapshot
 * growing. Databaseless runs should use FsStore instead.
 */
export class PostgresStore implements Store {
  private pool: Pool;

  constructor(private url: string) {
    this.pool = new Pool({ connectionString: url, max: 8 });
  }

  kind(): 'postgres' {
    return 'postgres';
  }

  async migrate(): Promise<void> {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const here = path.dirname(fileURLToPath(import.meta.url));
    const sqlPath = path.join(here, 'schema.sql');
    const sql = await fs.readFile(sqlPath, 'utf8');
    await this.pool.query(sql);
    log.info('store(postgres): schema ensured');
  }

  async loadPool(): Promise<Map<string, ProxyRecord>> {
    const { rows } = await this.pool.query('select * from proxies');
    return new Map(rows.map((r) => [r.key as string, rowToRecord(r)]));
  }

  async applyResults(results: CheckResultRecord[]): Promise<void> {
    for (const r of results) {
      const k = recordKey(r.protocol, r.host, r.port);
      const prev = await this.get(k);
      const next = prev ? applyResult(prev, r) : newRecord(r);
      await this.pool.query(
        `insert into proxies (
           key, protocol, host, port, user_, pass_, alive, latency_ms, remote_ip, anonymity,
           tls_issuer, tls_mitm, supports_tls, error, first_seen, last_ok, last_check,
           checks, ok_checks, fails, country, city, asn, org,
           uptime1h, uptime24h, uptime7d, uptime30d, latency_samples, seen_by, disabled_until
         ) values (
           $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
           to_timestamp($15/1000.0), to_timestamp($16/1000.0), to_timestamp($17/1000.0),
           $18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30
         )
         on conflict (key) do update set
           alive = excluded.alive, latency_ms = excluded.latency_ms, remote_ip = excluded.remote_ip,
           anonymity = excluded.anonymity, tls_issuer = excluded.tls_issuer, tls_mitm = excluded.tls_mitm,
           supports_tls = excluded.supports_tls, error = excluded.error, last_ok = excluded.last_ok,
           last_check = excluded.last_check, checks = excluded.checks, ok_checks = excluded.ok_checks,
           fails = excluded.fails, country = excluded.country, city = excluded.city, asn = excluded.asn,
           org = excluded.org, uptime1h = excluded.uptime1h, uptime24h = excluded.uptime24h,
           uptime7d = excluded.uptime7d, uptime30d = excluded.uptime30d,
           latency_samples = excluded.latency_samples, seen_by = excluded.seen_by,
           disabled_until = excluded.disabled_until`,
        [
          k,
          r.protocol,
          r.host,
          r.port,
          r.user ?? null,
          r.pass ?? null,
          r.alive,
          r.latencyMs,
          r.remoteIp,
          r.anonymity,
          r.tlsIssuer,
          r.tlsMitm,
          r.supportsTls,
          r.error,
          next.firstSeen,
          next.lastOk,
          next.lastCheck,
          next.checks,
          next.okChecks,
          next.fails,
          next.country,
          next.city,
          next.asn,
          next.org,
          next.uptime1h,
          next.uptime24h,
          next.uptime7d,
          next.uptime30d,
          next.latencySamples,
          next.seenBy,
          next.disabledUntil,
        ],
      );
    }
  }

  private async get(k: string): Promise<ProxyRecord | null> {
    const { rows } = await this.pool.query('select * from proxies where key = $1', [k]);
    return rows.length ? rowToRecord(rows[0]) : null;
  }

  async selectPending(opts: {
    limit: number;
    aliveAfterMs: number;
    retryFailedAfterMs: number;
    maxRecords: number;
  }): Promise<ProxyRecord[]> {
    const now = Date.now();
    const { rows } = await this.pool.query(
      `select * from proxies
       where (last_ok is null or last_ok < to_timestamp($1/1000.0))
         and (last_ok is null or last_check < to_timestamp($2/1000.0))
       order by last_ok asc nulls first
       limit $3`,
      [now - opts.aliveAfterMs, now - opts.retryFailedAfterMs, opts.limit],
    );
    if (rows.length) return rows.map(rowToRecord);
    // fall back: recently-seen-but-dead
    const { rows: rows2 } = await this.pool.query(
      `select * from proxies where last_ok is null order by last_check desc limit $1`,
      [Math.min(opts.limit, opts.maxRecords)],
    );
    return rows2.map(rowToRecord);
  }

  async prune(opts: { keepMax: number; deadAfterMs: number }): Promise<number> {
    const now = Date.now();
    const a = await this.pool.query(
      `delete from proxies where (last_ok is null or last_ok < to_timestamp($1/1000.0)) and fails >= 2`,
      [now - opts.deadAfterMs],
    );
    const b = await this.pool.query(
      `delete from proxies where key not in (
         select key from proxies order by coalesce(last_ok, 0) desc limit $1
       )`,
      [opts.keepMax],
    );
    return (a.rowCount ?? 0) + (b.rowCount ?? 0);
  }

  /** Write geo enrichment back (kept out of applyResults to keep it uniform). */
  async applyGeo(
    entries: Array<{
      key: string;
      country: string | null;
      city: string | null;
      asn: number | null;
      org: string | null;
    }>,
  ): Promise<void> {
    for (const e of entries) {
      await this.pool.query('update proxies set country = $2, city = $3, asn = $4, org = $5 where key = $1', [
        e.key,
        e.country,
        e.city,
        e.asn,
        e.org,
      ]);
    }
  }

  async flush(): Promise<void> {
    /* every statement is its own transaction */
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}

function rowToRecord(r: Record<string, unknown>): ProxyRecord {
  const ts = (v: unknown): number | null => (v instanceof Date ? v.getTime() : v === null ? null : Number(v));
  const num = (v: unknown): number | null => (v === null ? null : Number(v));
  return {
    key: String(r.key),
    protocol: String(r.protocol) as ProxyRecord['protocol'],
    host: String(r.host),
    port: Number(r.port),
    user: (r.user_ as string) ?? undefined,
    pass: (r.pass_ as string) ?? undefined,
    alive: Boolean(r.alive),
    latencyMs: num(r.latency_ms),
    remoteIp: (r.remote_ip as string) ?? null,
    anonymity: (r.anonymity as ProxyRecord['anonymity']) ?? 'unknown',
    tlsIssuer: (r.tls_issuer as string) ?? null,
    tlsMitm: Boolean(r.tls_mitm),
    supportsTls: Boolean(r.supports_tls),
    error: (r.error as string) ?? null,
    checkedAt: ts(r.last_check) ?? 0,
    seenBy: (r.seen_by as string[]) ?? [],
    firstSeen: ts(r.first_seen) ?? 0,
    lastOk: ts(r.last_ok),
    lastCheck: ts(r.last_check) ?? 0,
    checks: Number(r.checks ?? 0),
    okChecks: Number(r.ok_checks ?? 0),
    fails: Number(r.fails ?? 0),
    country: (r.country as string) ?? null,
    city: (r.city as string) ?? null,
    asn: num(r.asn),
    org: (r.org as string) ?? null,
    uptime1h: windowFrom(r.uptime1h),
    uptime24h: windowFrom(r.uptime24h),
    uptime7d: windowFrom(r.uptime7d),
    uptime30d: windowFrom(r.uptime30d),
    latencySamples: (r.latency_samples as number[]) ?? [],
    disabledUntil: ts(r.disabled_until),
  } satisfies ProxyRecord;
}

function windowFrom(v: unknown): [number, number] {
  if (Array.isArray(v) && v.length === 2) return [Number(v[0]), Number(v[1])];
  return [0, 0];
}
