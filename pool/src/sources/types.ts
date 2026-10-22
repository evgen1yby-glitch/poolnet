export type ProxyProtocol = 'http' | 'https' | 'socks4' | 'socks5';
export const SUPPORTED_PROTOCOLS: ProxyProtocol[] = ['http', 'socks4', 'socks5'];

export type SourceFormat = 'plain' | 'json' | 'html' | 'gfp' | 'spys' | 'advname' | 'roundproxies';

export interface SourceSpec {
  id: string;
  url: string;
  format: SourceFormat;
  protocol?: ProxyProtocol;
  enabled?: boolean;
  /**
   * Auth template for APIs that need a key, e.g. `bearer:${GFP_API_KEY}`.
   * `${VAR}` is expanded from the environment at load time; a source whose
   * variable is unset is skipped (never an error) so public CI without the
   * secret keeps working.
   */
  auth?: string;
  /** some directories serve the full table only via POST form parameters */
  method?: 'get' | 'post';
  /** urlencoded body for POST sources, e.g. "xpp=5" (500 rows per page) */
  body?: string;
}

export interface FetchedSource {
  spec: SourceSpec;
  ok: boolean;
  httpStatus: number | null;
  bytes: number;
  error?: string;
}

/** A candidate proxy, before any check. */
export interface Candidate {
  /** http | socks4 | socks5 */
  protocol: ProxyProtocol;
  host: string;
  port: number;
  /** source id where this candidate was seen in this cycle */
  source: string;
  /** optional credentials embedded in the source line */
  user?: string;
  pass?: string;
  /** country the source claims (our own geo pass remains authoritative) */
  country?: string;
}

export function canonicalKey(c: { protocol: string; host: string; port: number }): string {
  return `${c.protocol}://${c.host}:${c.port}`;
}

export function isValidIPv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return false;
  for (let i = 1; i <= 4; i++) {
    const n = Number(m[i]);
    if (n > 255) return false;
  }
  return true;
}

/** octets with leading zeros are the same host written differently */
export function normalizeIPv4(host: string): string {
  return host
    .split('.')
    .map((o) => String(Number(o)))
    .join('.');
}

/**
 * Publikoituva-osoite: the address must be routable on the public internet.
 * Skips 0/8, 10/8, CGNAT, loopback, link-local, the private 172.16/12 and
 * 192.168/16 ranges, documentation/test nets, multicast, the reserved block
 * and the broadcast address. A private address in the published list is not
 * a proxy anyone can use.
 */
export function isUsableIPv4(host: string): boolean {
  if (!isValidIPv4(host)) return false;
  const octets = host.split('.').map(Number);
  const [a, b] = octets;
  if (a === 0 || a === 10 || a === 127) return false; // unspecified, private, loopback
  if (a === 100 && b! >= 64 && b! <= 127) return false; // CGNAT 100.64/10
  if (a === 169 && b! === 254) return false; // link-local
  if (a === 172 && b! >= 16 && b! <= 31) return false; // 172.16/12
  if (a === 192 && b! === 168) return false; // 192.168/16
  if (a === 192 && b! === 0 && octets[2] === 2) return false; // TEST-NET-1
  if (a === 198 && (b! === 18 || b! === 19)) return false; // benchmarking
  if (a === 198 && b! === 51 && octets[2] === 100) return false; // TEST-NET-2
  if (a === 203 && b! === 0 && octets[2] === 113) return false; // TEST-NET-3
  if (a! >= 224) return false; // multicast, reserved, broadcast
  return true;
}

export function isValidPort(port: number): boolean {
  return Number.isInteger(port) && port > 0 && port <= 65535;
}

export function subnetOf(host: string): string {
  const parts = host.split('.');
  if (parts.length !== 4) return host;
  return parts.slice(0, 3).join('.');
}

/** Cheap deterministic hash for sharding. */
export function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}
