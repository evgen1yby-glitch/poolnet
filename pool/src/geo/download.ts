import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { config } from '../config.js';
import { log } from '../log.js';

/**
 * DB-IP publishes a free country database every month without a license
 * key, which keeps geo enrichment dependency-free in CI. We download the
 * current month on first use and keep it in the state directory; the file is
 * refreshed when it gets old so re-IP'd addresses do not keep their old
 * country.
 */
const MAX_AGE_DAYS = 35;
const DOWNLOAD = 'https://download.db-ip.com/free/dbip-country-lite-YYYY-MM.mmdb.gz';

function currentMonthUrl(now = new Date()): string {
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, '0');
  return DOWNLOAD.replace('YYYY-MM', `${y}-${m}`);
}

export function mmdbPath(): string {
  return path.join(config().stateDir, 'dbip-country-lite.mmdb');
}

export async function ensureMmdb(): Promise<string | null> {
  const target = mmdbPath();
  if (fs.existsSync(target) && fs.statSync(target).size > 10_000) {
    const ageDays = (Date.now() - fs.statSync(target).mtimeMs) / 86_400_000;
    if (ageDays < MAX_AGE_DAYS) return target;
    log.info(`geo: mmdb is ${ageDays.toFixed(0)} days old, refreshing`);
  }
  const url = process.env.OPP_GEOIP_URL || currentMonthUrl();
  log.info(`geo: downloading ${url}`);
  try {
    const res = await fetch(url, { headers: { 'User-Agent': config().fetchUserAgent } });
    if (!res.ok) {
      log.warn(`geo: download failed (${res.status}), country enrichment stays off`);
      return null;
    }
    const gz = Buffer.from(await res.arrayBuffer());
    fs.mkdirSync(config().stateDir, { recursive: true });
    fs.writeFileSync(target, zlib.gunzipSync(gz));
    log.info(`geo: mmdb ready at ${target} (${(fs.statSync(target).size / 1024 / 1024).toFixed(1)} MB)`);
    return target;
  } catch (e) {
    log.warn(`geo: ${(e as Error).message}, country enrichment stays off`);
    return null;
  }
}
