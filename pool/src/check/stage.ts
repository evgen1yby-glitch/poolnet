import tls from 'node:tls';
import { tcpConnect } from './net.js';
import net from 'node:net';
import { NET_CHECK, type EchoTarget } from './errors.js';
import { connectThrough, type ProxyTarget } from './proxy-client.js';
import { httpFallbackFor } from './targets.js';

export type Anonymity = 'transparent' | 'anonymous' | 'elite' | 'unknown';

export interface CheckOutcome {
  alive: boolean;
  stage: 'L1' | 'L2' | 'none';
  latencyMs: number | null;
  remoteIp: string | null;
  anonymity: Anonymity;
  headers: Record<string, string>;
  tlsIssuer: string | null;
  tlsMitm: boolean;
  supportsTls: boolean;
  error: string | null;
}

export interface CheckOptions {
  timeoutMs: number;
  stage1TimeoutMs: number;
  targets: EchoTarget[];
}

const IP_RE = /\b(\d{1,3}(?:\.\d{1,3}){3})\b/;

const CLIENT_LEAK_HEADERS = [
  'x-forwarded-for',
  'forwarded',
  'x-real-ip',
  'client-ip',
  'x-client-ip',
  'true-client-ip',
  'cf-connecting-ip',
];
const PROXY_HINTS = ['via', 'proxy-connection', 'x-proxy-id', 'x-bluecoat-via'];

/**
 * Body budget: echo payloads are a few KB. Proxies that stream more are not
 * useful for identity checks, and 250 concurrent reads must stay small.
 */
const MAX_BODY_BYTES = 256 * 1024;

// Known interception tools, plus issuers that are literally empty (an absent
// issuer means the tunnel was not end-to-end TLS). Anchored so a legitimate
// authority whose name merely contains one of these tokens - "None, LLC" is a
// real CA - is not flagged.
const MITM_TOOLS_RE =
  /(^|[^a-z])(mitm|mitmproxy|burp|fiddler|charles|zscaler|squid|tinyproxy|owasp|kaspersky|eset|avast|bitdefender|sslscan|sslsplit|tfsm)([^a-z]|$)/i;
const EMPTY_ISSUER_RE = /^\s*(none|\(none\)|-)?\s*$/i;

/** True when a certificate issuer means the tunnel is not end-to-end TLS. */
export function issuerIsMitm(raw: string): boolean {
  return MITM_TOOLS_RE.test(raw) || EMPTY_ISSUER_RE.test(raw);
}

/**
 * Full verification of one proxy, in two phases:
 *
 *  A) liveness: connect through the proxy and fetch a plain reachability
 *     target to completion (headers + full body). Cheap targets are the most
 *     permissive, so this is the stage that decides alive/dead.
 *  B) anonymity: a second request to an echo target that reports the inbound
 *     request headers; that view is what grades transparent/anonymous/elite.
 *
 * A proxy that passes A but fails B stays alive with grade "unknown".
 */
export async function checkProxy(proxy: ProxyTarget, opts: CheckOptions): Promise<CheckOutcome> {
  const started = Date.now();
  const deadline = started + opts.timeoutMs;

  // Liveness rides every target, rotated, so a rate-limited endpoint (429s
  // are common on public echo services) cannot sink the whole cycle.
  const order = rotateTargets(opts.targets, proxy);
  const a = await fetchThroughAny(proxy, order, deadline, opts.stage1TimeoutMs);
  if (!a.ok) {
    return dead(a.error, started, a);
  }

  const outcome: CheckOutcome = {
    alive: true,
    stage: 'L2',
    // only the request that succeeded counts; failing against the other
    // targets first is not latency the proxy imposed on this request
    latencyMs: a.elapsedMs ?? Date.now() - started,
    remoteIp: a.remoteIp,
    anonymity: a.headers ? gradeAnonymity(a.headers, proxy.host) : 'unknown',
    headers: a.headers ?? {},
    tlsIssuer: a.tlsIssuer,
    tlsMitm: a.tlsMitm,
    supportsTls: a.supportsTls,
    error: null,
  };

  // Phase B: grade anonymity on a header-bearing echo target. Some networks
  // block specific echo hosts, so every JSON target gets a turn.
  const succeededHost = a.targetHost ?? null;
  // the first liveness target is usually not an echo target, and echo hosts
  // fail individually: give up to three of them a turn before giving up on
  // grading, otherwise most of the pool stays ungraded
  for (const echoTarget of opts.targets
    .filter((t) => t.parser === 'json' && new URL(t.url).hostname !== succeededHost)
    .slice(0, 3)) {
    const b = await fetchThrough(proxy, echoTarget, deadline + 4000, opts.stage1TimeoutMs);
    if (b.ok && b.headers) {
      outcome.headers = b.headers;
      if (b.remoteIp) outcome.remoteIp = b.remoteIp;
      outcome.anonymity = gradeAnonymity(b.headers, proxy.host);
      if (b.tlsIssuer) outcome.tlsIssuer = b.tlsIssuer;
      if (b.tlsMitm) outcome.tlsMitm = true;
      break;
    }
  }
  return outcome;
}

/**
 * Order targets so consecutive checks spread across endpoints: public echo
 * services rate-limit per source IP, and a single hammered endpoint would
 * poison liveness results for the whole cycle. The rotation is keyed on the
 * proxy identity rather than the wall clock, so the same proxy gets the same
 * order in every run and a result never depends on when the cycle started.
 */
function rotateTargets(targets: EchoTarget[], proxy: ProxyTarget): EchoTarget[] {
  const n = targets.length;
  if (n <= 1) return targets;
  let h = 2166136261;
  for (const ch of `${proxy.protocol}://${proxy.host}:${proxy.port}`) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  const offset = Math.abs(h) % n;
  return [...targets.slice(offset), ...targets.slice(0, offset)];
}

/** Try every target in order; the first success wins. */
async function fetchThroughAny(
  proxy: ProxyTarget,
  targets: EchoTarget[],
  deadline: number,
  stage1TimeoutMs: number,
): Promise<Fetched & { targetHost?: string; elapsedMs?: number }> {
  let last: Fetched & { targetHost?: string; elapsedMs?: number } = {
    ok: false,
    status: 0,
    complete: false,
    remoteIp: null,
    headers: null,
    tlsIssuer: null,
    tlsMitm: false,
    supportsTls: false,
    error: 'no targets',
  };
  for (const t of targets) {
    const attemptStart = Date.now();
    const res = await fetchThrough(proxy, t, deadline, stage1TimeoutMs);
    last = { ...res, targetHost: new URL(t.url).hostname, elapsedMs: Date.now() - attemptStart };
    if (res.ok) return last;
  }
  return last;
}

interface Fetched {
  /** wall-clock duration of this attempt alone */
  elapsedMs?: number;
  ok: boolean;
  status: number;
  complete: boolean;
  remoteIp: string | null;
  headers: Record<string, string> | null;
  tlsIssuer: string | null;
  tlsMitm: boolean;
  supportsTls: boolean;
  error: string | null;
}

/**
 * Fetch `target` through the proxy. HTTP proxies that refuse CONNECT fall
 * back to an absolute-form GET, which covers the CDN-fronted open proxies
 * that only speak plain HTTP.
 */
async function fetchThrough(
  proxy: ProxyTarget,
  target: EchoTarget,
  deadline: number,
  stage1TimeoutMs: number,
): Promise<Fetched> {
  const budget = () => Math.max(500, deadline - Date.now());
  const u = new URL(target.url);
  const isTls = u.protocol === 'https:';
  const port = u.port ? Number(u.port) : isTls ? 443 : 80;
  try {
    const conn = await connectThrough(proxy, u.hostname, port, Math.min(budget(), stage1TimeoutMs));
    try {
      // whatever the proxy already sent after the handshake belongs to this
      // request: a coalesced reply must not be read as an empty response
      const initial = conn.reader.detach();
      const res = await fetchOver(conn.sock, initial, u.hostname, u.pathname + u.search, isTls, budget());
      return interpret(res, isTls);
    } finally {
      conn.sock.destroy();
    }
  } catch (e) {
    if (proxy.protocol !== 'http') {
      return {
        ok: false,
        status: 0,
        complete: false,
        remoteIp: null,
        headers: null,
        tlsIssuer: null,
        tlsMitm: false,
        supportsTls: false,
        error: e instanceof NET_CHECK ? e.message : String(e),
      };
    }
    try {
      const httpT = httpFallbackFor(target);
      return await plainHttpGet(proxy, httpT, budget);
    } catch (e2) {
      return {
        ok: false,
        status: 0,
        complete: false,
        remoteIp: null,
        headers: null,
        tlsIssuer: null,
        tlsMitm: false,
        supportsTls: false,
        error: e2 instanceof NET_CHECK ? e2.message : String(e2),
      };
    }
  }
}

function interpret(res: HttpResult, isTls: boolean): Fetched {
  const ok = res.status >= 200 && res.status < 400 && res.complete;
  const echo = parseEcho(res.body);
  return {
    ok,
    status: res.status,
    complete: res.complete,
    remoteIp: echo.remoteIp,
    headers: echo.headers,
    tlsIssuer: res.tlsIssuer,
    tlsMitm: res.tlsMitm,
    supportsTls: isTls,
    error: ok ? null : `HTTP ${res.status} complete=${res.complete}`,
  };
}

function dead(error: string | null, started: number, fetched?: Fetched): CheckOutcome {
  return {
    alive: false,
    stage: 'none',
    latencyMs: null,
    remoteIp: fetched?.remoteIp ?? null,
    anonymity: 'unknown',
    headers: fetched?.headers ?? {},
    tlsIssuer: fetched?.tlsIssuer ?? null,
    tlsMitm: fetched?.tlsMitm ?? false,
    supportsTls: fetched?.supportsTls ?? false,
    error: error ?? 'dead',
  };
}

/** Absolute-form GET through the proxy without CONNECT. */
async function plainHttpGet(proxy: ProxyTarget, target: EchoTarget, budget: () => number): Promise<Fetched> {
  const sock = await tcpConnect(proxy.host, proxy.port, budget());
  try {
    sock.write(
      `GET ${target.url} HTTP/1.1\r\nHost: ${new URL(target.url).host}\r\n` +
        `User-Agent: open-proxy-pool/0.1\r\nAccept: */*\r\nConnection: close\r\n\r\n`,
    );
    const res = await readHttpResponse(sock, Buffer.alloc(0), budget());
    return interpret({ ...res, supportsTls: false, tlsIssuer: null, tlsMitm: false }, false);
  } finally {
    sock.destroy();
  }
}

/** Send a relative GET over an already-established tunnel, read the full body. */
async function fetchOver(
  sock: net.Socket,
  initial: Buffer,
  host: string,
  path: string,
  isTls: boolean,
  timeoutMs: number,
): Promise<HttpResult> {
  let tlsIssuer: string | null = null;
  let tlsMitm = false;
  let transport: net.Socket = sock;
  if (isTls) {
    const ts = await tlsConnectWithTimeout(sock, { servername: host, rejectUnauthorized: false }, timeoutMs);
    transport = ts;
    const cert = ts.getPeerCertificate();
    if (cert && cert.issuer) {
      const org = cert.issuer.O ?? '';
      const cn = cert.issuer.CN ?? '';
      const raw = [org, cn].filter(Boolean).join(' / ') || '';
      tlsIssuer = raw !== '' ? raw : null;
      const now = Date.now();
      const from = cert.valid_from ? Date.parse(cert.valid_from) : 0;
      const to = cert.valid_to ? Date.parse(cert.valid_to) : 0;
      const expired = (from && now < from) || (to && now > to);
      if (issuerIsMitm(raw) || expired) tlsMitm = true;
    }
  }
  transport.write(
    `GET ${path} HTTP/1.1\r\nHost: ${host}\r\n` +
      `User-Agent: open-proxy-pool/0.1\r\nAccept: */*\r\nConnection: close\r\n\r\n`,
  );
  const res = await readHttpResponse(transport, initial, timeoutMs);
  return { ...res, supportsTls: isTls, tlsIssuer, tlsMitm };
}

/** tls.connect with a hard deadline: a proxy can accept a tunnel and then go
 *  silent mid-handshake, and nothing else would ever end that await. */
function tlsConnectWithTimeout(sock: net.Socket, opts: tls.ConnectionOptions, ms: number): Promise<tls.TLSSocket> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(t);
      fn();
    };
    const t = setTimeout(() => {
      done(() => {
        try {
          sock.destroy();
        } catch {
          /* ignore */
        }
        reject(new NET_CHECK('tls handshake timeout'));
      });
    }, ms);
    const ts = tls.connect({ ...opts, socket: sock });
    ts.once('secureConnect', () => done(() => resolve(ts)));
    ts.once('error', (e) =>
      done(() => {
        try {
          sock.destroy();
        } catch {
          /* ignore */
        }
        reject(new NET_CHECK(`tls: ${e.message}`));
      }),
    );
  });
}

interface HttpResult {
  status: number;
  headers: Record<string, string>;
  body: string;
  complete: boolean;
  supportsTls: boolean;
  tlsIssuer: string | null;
  tlsMitm: boolean;
}

async function readHttpResponse(
  sock: net.Socket,
  initial: Buffer,
  timeoutMs: number,
): Promise<{ status: number; headers: Record<string, string>; body: string; complete: boolean }> {
  let buf = initial;
  let truncated = false;
  await new Promise<void>((resolve) => {
    const t = setTimeout(() => {
      sock.removeAllListeners('data');
      resolve();
    }, timeoutMs);
    sock.on('data', (d) => {
      if (buf.length >= MAX_BODY_BYTES) {
        truncated = true;
        return;
      }
      buf = Buffer.concat([buf, d]);
      if (buf.length >= MAX_BODY_BYTES) {
        truncated = true;
        buf = buf.subarray(0, MAX_BODY_BYTES);
      }
    });
    sock.once('error', () => {
      clearTimeout(t);
      resolve();
    });
    sock.once('end', () => {
      clearTimeout(t);
      resolve();
    });
    sock.once('close', () => {
      clearTimeout(t);
      resolve();
    });
  });
  const text = buf.toString('latin1');
  const idx = text.indexOf('\r\n\r\n');
  if (idx < 0) {
    const statusLine = text.split('\r\n')[0] ?? '';
    const m = /^HTTP\/1\.[01] (\d{3})/.exec(statusLine);
    return { status: m ? Number(m[1]) : 0, headers: {}, body: '', complete: false };
  }
  const head = text.slice(0, idx);
  const body = text.slice(idx + 4);
  const lines = head.split('\r\n');
  const statusMatch = /^HTTP\/1\.[01] (\d{3})/.exec(lines[0] ?? '');
  if (!statusMatch) throw new NET_CHECK('malformed status line');
  const headers: Record<string, string> = {};
  for (const line of lines.slice(1)) {
    const c = line.indexOf(':');
    if (c > 0) headers[line.slice(0, c).trim().toLowerCase()] = line.slice(c + 1).trim();
  }
  let complete = !truncated;
  const cl = headers['content-length'];
  if (cl) {
    complete = complete && Buffer.byteLength(body, 'latin1') >= Number(cl);
  } else if (headers['transfer-encoding']?.includes('chunked')) {
    complete = complete && /0\r\n\r\n$/.test(body);
  }
  return { status: Number(statusMatch[1]), headers, body, complete };
}

interface Echo {
  remoteIp: string | null;
  headers: Record<string, string> | null;
}

function parseEcho(body: string): Echo {
  const trimmed = body.trim();
  if (!trimmed) return { remoteIp: null, headers: null };
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const j = JSON.parse(trimmed) as Record<string, unknown>;
      const origin = typeof j.origin === 'string' ? j.origin : typeof j.remote_addr === 'string' ? j.remote_addr : null;
      const headers = (j.headers && typeof j.headers === 'object' ? j.headers : null) as Record<string, string> | null;
      let remoteIp: string | null = null;
      if (origin) {
        const m = IP_RE.exec(origin);
        if (m) remoteIp = m[1] ?? null;
      }
      return { remoteIp, headers: normalizeHeaders(headers) };
    } catch {
      /* fall through to text */
    }
  }
  const m = IP_RE.exec(trimmed);
  return { remoteIp: m ? (m[1] ?? null) : null, headers: null };
}

function normalizeHeaders(h: Record<string, string> | null): Record<string, string> | null {
  if (!h) return null;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(h)) out[String(k).toLowerCase()] = String(v);
  return out;
}

/** Anonymity grade from the target's own view of the request. */
export function gradeAnonymity(headers: Record<string, string>, proxyHost: string): Anonymity {
  for (const h of CLIENT_LEAK_HEADERS) {
    const v = headers[h];
    if (typeof v === 'string' && v) {
      const m = IP_RE.exec(v);
      if (m && m[1] !== proxyHost) return 'transparent';
      if (m && m[1] === proxyHost) return 'anonymous';
    }
  }
  for (const h of PROXY_HINTS) {
    if (headers[h]) return 'anonymous';
  }
  return 'elite';
}
