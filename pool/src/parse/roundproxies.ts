import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * roundproxies.com/free-proxy-list — 100 server-rendered rows per page with
 * rich metadata the source publishes itself: address, port, checks passed,
 * country, speed, protocol, uptime, org and anonymity grade. The pipe keeps
 * the operational fields as claims; our checker still measures everything.
 *
 * Row shape (12 cells):
 *   addr | port | checks | country | speed | protocol | .. | .. | org | uptime | .. | grade
 */
const ROW_RE = /<tr[^>]*>\s*<td[^>]*>(\d{1,3}(?:\.\d{1,3}){3})<\/td>\s*<td[^>]*>(\d{1,5})<\/td>([\s\S]*?)<\/tr>/g;
const CELL_RE = /<td[^>]*>([\s\S]*?)<\/td>/g;
const CLEAN_RE = /<[^>]+>/g;

const PROTOCOLS = new Set<ProxyProtocol>(['http', 'socks4', 'socks5']);

interface RowMeta {
  country: string | null;
  /** null when the row does not name a protocol — caller falls back */
  protocol: ProxyProtocol | null;
  latency: number | null;
  uptime: number | null;
  org: string | null;
  anonymity: string | null;
}

function cells(html: string): string[] {
  return [...html.matchAll(CELL_RE)].map((m) => m[1]!.replace(CLEAN_RE, '').trim());
}

function parseRow(cellList: string[]): RowMeta {
  let country: string | null = null;
  let protocol: ProxyProtocol | null = null;
  let latency: number | null = null;
  let uptime: number | null = null;
  let org: string | null = null;
  let anonymity: string | null = null;

  for (const raw of cellList) {
    const v = raw.trim();
    if (!v) continue;
    const cc = /^([A-Z]{2})$/.exec(v);
    if (cc && !country) {
      country = cc[1]!;
      continue;
    }
    const proto = /^(http|https|socks4|socks5|socks4a)$/i.exec(v);
    if (proto) {
      const p = proto[1]!.toLowerCase();
      protocol = (p === 'https' ? 'http' : p === 'socks4a' ? 'socks4' : p) as ProxyProtocol;
      continue;
    }
    const lat = /^([\d.]+)\s*ms$/i.exec(v);
    if (lat) {
      latency = Math.round(Number(lat[1]));
      continue;
    }
    const up = /^([\d.]+)%$/.exec(v);
    if (up) {
      uptime = Math.round(Number(up[1]));
      continue;
    }
    const anon = /^(elite|anonymous|transparent|noa|hia|anm)$/i.exec(v);
    if (anon) {
      const a = anon[1]!.toLowerCase();
      anonymity = a === 'noa' ? 'transparent' : a === 'hia' ? 'elite' : a === 'anm' ? 'anonymous' : a;
      continue;
    }
    if (!org && v.length > 2 && /[A-Za-z]/.test(v) && !/^\d/.test(v)) org = v;
  }
  return { country, protocol, latency, uptime, org, anonymity };
}

export function parseRoundproxies(html: string, defaultProtocol: ProxyProtocol): Candidate[] {
  const out: Candidate[] = [];
  for (const m of html.matchAll(ROW_RE)) {
    const host = m[1]!;
    const port = Number(m[2]);
    if (!isUsableIPv4(host) || !isValidPort(port)) continue;
    const meta = parseRow(cells(m[3] ?? ''));
    const protocol = meta.protocol && PROTOCOLS.has(meta.protocol) ? meta.protocol : defaultProtocol;
    const c: Candidate = { protocol, host, port, source: '' };
    if (meta.country) c.country = meta.country;
    out.push(c);
  }
  return out;
}
