import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { log } from '../log.js';
import { applyResult, newRecord, recordKey, type CheckResultRecord, type ProxyRecord, type Store } from './types.js';

interface FileShape {
  version: 1;
  savedAt: number;
  proxies: ProxyRecord[];
}

/**
 * Zero-dependency store: one gzipped JSON snapshot.
 * Perfect for GitHub Actions: the snapshot rides along as a cache/artifact,
 * so the pipeline needs no database to work.
 */
export class FsStore implements Store {
  private map = new Map<string, ProxyRecord>();
  private loaded = false;

  constructor(private file: string) {}

  kind(): 'fs' {
    return 'fs';
  }

  private load(): void {
    if (this.loaded) return;
    this.loaded = true;
    try {
      const buf = fs.readFileSync(this.file);
      const parsed = JSON.parse(zlib.gunzipSync(buf).toString('utf8')) as FileShape;
      for (const rec of parsed.proxies) {
        if (rec && rec.key) this.map.set(rec.key, rec);
      }
      log.info(`store: loaded ${this.map.size} records from ${this.file}`);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === 'ENOENT') return; // first run
      // a partially written or corrupt snapshot would silently reset every
      // uptime window, rank and geo fact the moment it is flushed back
      throw new Error(`store: ${this.file} is unreadable (${(e as Error).message}); move it aside and retry`);
    }
  }

  async loadPool(): Promise<Map<string, ProxyRecord>> {
    this.load();
    return this.map;
  }

  async applyResults(results: CheckResultRecord[]): Promise<void> {
    this.load();
    for (const r of results) {
      const k = recordKey(r.protocol, r.host, r.port);
      const prev = this.map.get(k);
      this.map.set(k, prev ? applyResult(prev, r) : newRecord(r));
    }
  }

  async applyGeo(entries: import('./types.js').GeoEntry[]): Promise<void> {
    this.load();
    for (const e of entries) {
      const rec = this.map.get(e.key);
      if (!rec) continue;
      rec.country = e.country;
      rec.city = e.city;
      rec.asn = e.asn;
      rec.org = e.org;
    }
  }

  async selectPending(opts: {
    limit: number;
    aliveAfterMs: number;
    retryFailedAfterMs: number;
    maxRecords: number;
  }): Promise<ProxyRecord[]> {
    this.load();
    const now = Date.now();
    const pool = [...this.map.values()];
    // bound the store first: drop the oldest, noisiest records
    pool.sort((a, b) => (b.lastOk ?? 0) - (a.lastOk ?? 0) || b.okChecks / b.checks - a.okChecks / a.checks);
    while (pool.length > opts.maxRecords) {
      const drop = pool.pop()!;
      this.map.delete(drop.key);
    }
    const due: ProxyRecord[] = [];
    for (const rec of this.map.values()) {
      const lastOk = rec.lastOk ?? 0;
      const sinceCheck = now - rec.lastCheck;
      if (lastOk > now - opts.aliveAfterMs) continue; // fresh, skip
      const failed = rec.fails >= 1 && lastOk < now - opts.aliveAfterMs;
      if (failed && sinceCheck < opts.retryFailedAfterMs) continue;
      due.push(rec);
    }
    due.sort((a, b) => (a.lastOk ?? 0) - (b.lastOk ?? 0));
    return due.slice(0, opts.limit);
  }

  async prune(opts: { keepMax: number; deadAfterMs: number }): Promise<number> {
    this.load();
    const now = Date.now();
    let removed = 0;
    for (const [k, rec] of this.map) {
      const lastOk = rec.lastOk ?? 0;
      if (now - lastOk > opts.deadAfterMs) {
        this.map.delete(k);
        removed++;
      }
    }
    if (this.map.size > opts.keepMax) {
      const sorted = [...this.map.values()].sort((a, b) => (a.lastOk ?? 0) - (b.lastOk ?? 0));
      const drop = this.map.size - opts.keepMax;
      for (let i = 0; i < drop; i++) {
        this.map.delete(sorted[i]!.key);
        removed++;
      }
    }
    return removed;
  }

  async flush(): Promise<void> {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const shape: FileShape = { version: 1, savedAt: Date.now(), proxies: [...this.map.values()] };
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, zlib.gzipSync(JSON.stringify(shape), { level: 6 }));
    fs.renameSync(tmp, this.file);
    log.info(`store: saved ${this.map.size} records -> ${this.file}`);
  }

  async close(): Promise<void> {
    await this.flush();
  }
}
