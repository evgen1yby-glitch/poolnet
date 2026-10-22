import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * advanced.name/freeproxy — 100 rows per page, 5 pages (~485 entries).
 * The address and port are base64 attribute values; the type is an anchor
 * (`?type=socks4`) and the country comes from the flag class
 * (`flag-free-us`). All three ride along in the row slice.
 */
const ROW_RE = /<td data-ip="([^"]+)"[^>]*><\/td>\s*<td data-port="([^"]+)"[^>]*><\/td>([\s\S]{0,1600}?)<\/tr>/g;
const TYPE_RE = /\/freeproxy\?type=(socks4|socks5|http|https)[^"]*"[^>]*>\s*(?:SOCKS4|SOCKS5|HTTP|HTTPS)\s*</i;
const TYPE_TEXT_RE = /class="label label-\w+">\s*(HTTP|HTTPS|SOCKS4|SOCKS5)\s*</i;
const COUNTRY_RE = /flag-free-([a-z]{2})\b/i;

function decodeB64(v: string): string | null {
  try {
    const s = Buffer.from(v, 'base64').toString('utf8');
    return /^[\x20-\x7e]+$/.test(s) ? s : null;
  } catch {
    return null;
  }
}

const PROTOCOL_BY_TYPE: Record<string, ProxyProtocol | null> = {
  HTTP: 'http',
  HTTPS: 'http',
  SOCKS4: 'socks4',
  SOCKS5: 'socks5',
};

export function parseAdvancedName(html: string, defaultProtocol: ProxyProtocol): Candidate[] {
  const out: Candidate[] = [];
  for (const m of html.matchAll(ROW_RE)) {
    const host = decodeB64(m[1]!);
    const portRaw = decodeB64(m[2]!);
    if (!host || !portRaw) continue;
    const port = Number(portRaw);
    if (!isUsableIPv4(host) || !isValidPort(port)) continue;

    const slice = m[3] ?? '';
    const typeRaw = TYPE_RE.exec(slice)?.[1] ?? TYPE_TEXT_RE.exec(slice)?.[1];
    const type = typeRaw ? typeRaw.toUpperCase() : null;
    const protocol = (type && PROTOCOL_BY_TYPE[type]) || defaultProtocol;
    const country = COUNTRY_RE.exec(slice)?.[1]?.toUpperCase() ?? null;

    const c: Candidate = { protocol, host, port, source: '' };
    if (country) c.country = country;
    out.push(c);
  }
  return out;
}
