/**
 * Use the pool from Node: filter it like the website does, then hand out
 * one working proxy at a time.
 *
 *   node examples/rotate.mjs            # top 10 elite proxies
 *   node examples/rotate.mjs socks5 US  # top 10 socks5 from the US
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const poolFile = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'proxies.json');
const [, , wantProtocol, wantCountry] = process.argv;

const pool = JSON.parse(fs.readFileSync(poolFile, 'utf8'));
let entries = pool.proxies ?? pool;
if (wantProtocol) entries = entries.filter((p) => p.protocol === wantProtocol);
if (wantCountry) entries = entries.filter((p) => p.country === wantCountry);

// the file is published best-first; keep elite, then drop TLS-MITM exits
const picks = entries
  .filter((p) => p.anonymity === 'elite' && !p.tls_mitm)
  .slice(0, 10);

if (!picks.length) {
  console.error('no elite proxies for that filter — widen it');
  process.exit(1);
}

console.log(`${picks.length} proxies (of ${entries.length} matching):`);
for (const p of picks) {
  const line = `${p.protocol}://${p.host}:${p.port}`;
  const where = [p.city, p.country].filter(Boolean).join(', ');
  console.log(`  ${line.padEnd(30)} ${String(p.latency_ms ?? '?').padStart(6)} ms  ${p.uptime_7d ?? '?'}% 7d  ${where}`);
}

console.log('\ncurl example:');
console.log(`  curl -x socks5h://${picks[0].host}:${picks[0].port} https://api.ipify.org`);
