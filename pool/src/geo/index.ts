import fs from 'node:fs';
import maxmind from 'maxmind';
import { log } from '../log.js';
import { config } from '../config.js';
import { ensureMmdb, mmdbPath } from './download.js';

export interface GeoInfo {
  country: string | null;
  city: string | null;
  asn: number | null;
  org: string | null;
}

export const EMPTY_GEO: GeoInfo = { country: null, city: null, asn: null, org: null };

/** MaxMind rows as far as we consume them (Country or City DB both fit). */
type GeoRow = maxmind.CityResponse;

let readerPromise: Promise<maxmind.Reader<GeoRow> | null> | null = null;

/**
 * Provider resolution: an explicit mmdb path wins; `auto` downloads the free
 * DB-IP country database on first use; `ipapi` and `none` never touch disk.
 */
async function resolveMmdbPath(): Promise<string | null> {
  const cfg = config();
  if (cfg.geoipMmdbPath) return cfg.geoipMmdbPath;
  if (cfg.geoipProvider === 'auto' || process.env.OPP_GEOIP_PROVIDER === 'auto') {
    return ensureMmdb();
  }
  return mmdbPath() && fs.existsSync(mmdbPath()) ? mmdbPath() : null;
}

function mmdbReader(): Promise<maxmind.Reader<GeoRow> | null> {
  if (readerPromise) return readerPromise;
  readerPromise = (async () => {
    const p = await resolveMmdbPath();
    if (!p) return null;
    try {
      const r = await maxmind.open<GeoRow>(p);
      log.info(`geo: loaded mmdb ${p}`);
      return r;
    } catch (e) {
      log.warn(`geo: cannot open ${p}: ${(e as Error).message}`);
      return null;
    }
  })();
  return readerPromise;
}

export async function geoReady(): Promise<boolean> {
  return (await mmdbReader()) !== null;
}

/** Batch lookup: one call for all entries of a cycle. */
export async function geoLookup(ips: string[]): Promise<Map<string, GeoInfo>> {
  const out = new Map<string, GeoInfo>();
  if (ips.length === 0) return out;
  const cfg = config();
  if (cfg.geoipProvider === 'mmdb' || cfg.geoipProvider === 'auto') {
    const r = await mmdbReader();
    if (!r) return out;
    for (const ip of ips) {
      try {
        const res = r.get(ip);
        out.set(ip, {
          country: res?.country?.iso_code ?? null,
          city: res?.city?.names?.en ?? null,
          asn: res?.traits?.autonomous_system_number ?? null,
          org: res?.traits?.autonomous_system_organization ?? null,
        });
      } catch {
        out.set(ip, EMPTY_GEO);
      }
    }
    return out;
  }
  if (cfg.geoipProvider === 'ipapi') {
    return ipApiBatch(ips);
  }
  return out;
}

/** Free tier: batches of 100, ~15 req/min. Falls back silently to nulls. */
async function ipApiBatch(ips: string[]): Promise<Map<string, GeoInfo>> {
  const out = new Map<string, GeoInfo>();
  for (let i = 0; i < ips.length; i += 100) {
    const chunk = ips.slice(i, i + 100);
    try {
      const res = await fetch('http://ip-api.com/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(chunk.map((query) => ({ query, fields: 'status,countryCode,city,as,query', lang: 'en' }))),
      });
      const json = (await res.json()) as Array<{
        status: string;
        countryCode?: string;
        city?: string;
        as?: string;
        query?: string;
      }>;
      for (const row of json) {
        const asnMatch = row.as ? /^AS(\d+)/.exec(row.as) : null;
        out.set(row.query ?? '', {
          country: row.countryCode ?? null,
          city: row.city ?? null,
          asn: asnMatch ? Number(asnMatch[1]) : null,
          org: row.as ? row.as.replace(/^AS\d+\s*/, '') : null,
        });
      }
    } catch (e) {
      log.warn(`geo: ip-api batch failed: ${(e as Error).message}`);
    }
  }
  return out;
}

export function fileExists(p: string): boolean {
  return fs.existsSync(p);
}
