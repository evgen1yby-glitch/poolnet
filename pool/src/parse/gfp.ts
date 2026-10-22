import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * getfreeproxy.com API records:
 *   [{ "protocol": "socks5", "ip": "...", "port": 1080, "user": "", "passwd": "",
 *      "anonymity": "HIA", "uptime": 77, "responseTime": 2.69,
 *      "lastAliveAt": "...", "countryCode": "US", "proxyUrl": "socks5://…" }]
 *
 * The list also carries vmess/vless entries — real proxies, but protocols
 * this pipeline cannot speak. They are skipped here, exactly like unknown
 * schemes in plain text sources.
 */
export function parseGfp(text: string): Candidate[] {
  let rows: unknown;
  try {
    rows = JSON.parse(text);
  } catch {
    return [];
  }
  if (!Array.isArray(rows)) return [];

  const out: Candidate[] = [];
  for (const row of rows) {
    if (row === null || typeof row !== 'object') continue;
    const r = row as {
      protocol?: unknown;
      ip?: unknown;
      port?: unknown;
      user?: unknown;
      passwd?: unknown;
      countryCode?: unknown;
      responseTime?: unknown;
      lastAliveAt?: unknown;
      anonymity?: unknown;
    };
    const ip = typeof r.ip === 'string' ? r.ip : null;
    const port = typeof r.port === 'number' ? r.port : typeof r.port === 'string' ? Number(r.port) : NaN;
    const proto = typeof r.protocol === 'string' ? r.protocol.toLowerCase() : '';
    if (!ip || !Number.isFinite(port)) continue;
    if (!isUsableIPv4(ip) || !isValidPort(port)) continue;

    // vmess/vless/trojan/ssr and friends are not verifiable here
    const protocol: ProxyProtocol | null =
      proto === 'socks5'
        ? 'socks5'
        : proto === 'socks4'
          ? 'socks4'
          : proto === 'http' || proto === 'https'
            ? 'http'
            : null;
    if (!protocol) continue;

    // the API spells missing credentials as the string "null" as often as ""
    const cred = (v: unknown): string | undefined =>
      typeof v === 'string' && v.length > 0 && v !== 'null' ? v : undefined;
    const user = cred(r.user);
    const pass = cred(r.passwd);
    const c: Candidate = { protocol, host: ip, port, source: '' };
    if (user) c.user = user;
    if (pass) c.pass = pass;
    out.push(c);
  }
  return out;
}
