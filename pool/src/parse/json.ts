import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * Parse geonode-style payloads:
 * { "data": [ { "ip": "...", "port": 1080, "protocols": ["socks5"] } ] }
 * The first supported protocol present wins (socks5 > http > socks4).
 */
export function parseJsonSource(text: string, defaultProtocol: ProxyProtocol): Candidate[] {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return [];
  }
  const obj = payload as { data?: unknown };
  if (!obj || !Array.isArray(obj.data)) return [];
  const out: Candidate[] = [];
  for (const entry of obj.data) {
    const e = entry as { ip?: unknown; port?: unknown; protocols?: unknown };
    const ip = typeof e.ip === 'string' ? e.ip : null;
    const port = typeof e.port === 'number' ? e.port : typeof e.port === 'string' ? Number(e.port) : NaN;
    if (!ip || !Number.isFinite(port)) continue;
    if (!isUsableIPv4(ip) || !isValidPort(port)) continue;
    const protocols = Array.isArray(e.protocols) ? e.protocols.filter((p): p is string => typeof p === 'string') : [];
    const protocol: ProxyProtocol = protocols.includes('socks5')
      ? 'socks5'
      : protocols.includes('http')
        ? 'http'
        : protocols.includes('socks4')
          ? 'socks4'
          : defaultProtocol;
    out.push({ protocol, host: ip, port, source: '' });
  }
  return out;
}
