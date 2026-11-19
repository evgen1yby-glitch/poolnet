import { parseProxyLine } from './plain.js';
import {
  isUsableIPv4,
  isValidPort,
  normalizeIPv4,
  type Candidate,
  type ProxyProtocol,
} from '../sources/types.js';

/**
 * Parse the JSON shapes published by the free-proxy APIs we consume.
 *
 * Supported payloads:
 *   geonode / roundproxies: { "data": [ { ip, port, protocols: ["socks5"] } ] }
 *   charlespikachu:         { "data": [ { ip, port, protocol: "Socks5" } ] }
 *   mauricegift:            { "proxies": [ "ip:port", ... ] }
 *   proxytee:               { "proxies": [ { host, port, proxy_type, types } ] }
 *
 * Entries may carry several protocols at once ("Http, Socks5"); the first
 * supported one in the project's precedence (socks5 > http > socks4) wins.
 */
export function parseJsonSource(text: string, defaultProtocol: ProxyProtocol): Candidate[] {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return [];
  }
  if (!payload || typeof payload !== 'object') return [];
  const obj = payload as Record<string, unknown>;
  const entries = Array.isArray(obj.data)
    ? obj.data
    : Array.isArray(obj.proxies)
      ? obj.proxies
      : [];
  const out: Candidate[] = [];
  for (const entry of entries) {
    const candidate = parseEntry(entry, defaultProtocol);
    if (candidate) out.push(candidate);
  }
  return out;
}

function parseEntry(entry: unknown, defaultProtocol: ProxyProtocol): Candidate | null {
  if (typeof entry === 'string') return parseProxyLine(entry, defaultProtocol);
  if (!entry || typeof entry !== 'object') return null;

  const e = entry as Record<string, unknown>;
  const ip =
    typeof e.ip === 'string' ? e.ip : typeof e.host === 'string' ? e.host : null;
  const port =
    typeof e.port === 'number' ? e.port : typeof e.port === 'string' ? Number(e.port) : NaN;
  if (!ip || !Number.isFinite(port)) return null;

  const host = normalizeIPv4(ip);
  if (!isUsableIPv4(host) || !isValidPort(port)) return null;

  const declared = [
    ...(Array.isArray(e.protocols) ? e.protocols : []),
    e.protocol,
    e.proxy_type,
    ...(Array.isArray(e.types)
      ? e.types.map((t) => (t && typeof t === 'object' ? (t as Record<string, unknown>).type : undefined))
      : []),
  ];
  const protocol = pickProtocol(declared) ?? defaultProtocol;

  return { protocol, host, port, source: '' };
}

function pickProtocol(values: unknown[]): ProxyProtocol | null {
  const found: ProxyProtocol[] = [];
  for (const value of values) {
    if (typeof value !== 'string') continue;
    for (const token of value.split(/[,/|\s]+/)) {
      const p = tokenToProtocol(token);
      if (p) found.push(p);
    }
  }
  if (found.includes('socks5')) return 'socks5';
  if (found.includes('http')) return 'http';
  if (found.includes('socks4')) return 'socks4';
  return null;
}

function tokenToProtocol(token: string): ProxyProtocol | null {
  const v = token.toLowerCase();
  if (v.startsWith('socks5')) return 'socks5';
  if (v.startsWith('socks4')) return 'socks4';
  if (v.startsWith('http')) return 'http';
  return null;
}
