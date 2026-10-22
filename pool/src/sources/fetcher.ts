import { config } from '../config.js';
import { log } from '../log.js';

export interface FetchResult {
  spec: import('./types.js').SourceSpec;
  status: number | null;
  body: string;
  ok: boolean;
  error?: string;
  /** Content freshness signals: independent sources can be 200 yet unmaintained */
  lastModified: string | null;
}

interface GetOpts {
  method?: 'get' | 'post';
  body?: string;
}

async function get(
  url: string,
  redirects: number,
  ua: string,
  timeoutMs: number,
  auth?: string,
  opts: GetOpts = {},
): Promise<{ status: number; body: string; lastModified: string | null }> {
  if (redirects > 3) throw new Error('too many redirects');
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  const headers: Record<string, string> = { 'User-Agent': ua, Accept: '*/*' };
  if (auth?.startsWith('bearer:')) {
    headers.Authorization = `Bearer ${auth.slice(7)}`;
  }
  try {
    const method = opts.method === 'post' ? 'POST' : 'GET';
    if (method === 'POST') headers['Content-Type'] = 'application/x-www-form-urlencoded';
    const res = await fetch(url, {
      method,
      headers,
      body: method === 'POST' ? (opts.body ?? '') : undefined,
      redirect: 'manual',
      signal: ac.signal,
    });
    if (res.status >= 300 && res.status < 400 && res.headers.get('location')) {
      const next = new URL(res.headers.get('location')!, url).toString();
      return get(next, redirects + 1, ua, timeoutMs, auth, opts);
    }
    const body = await res.text();
    return { status: res.status, body, lastModified: res.headers.get('last-modified') };
  } finally {
    clearTimeout(timer);
  }
}

/** Fetch one source. Never throws: errors are reported in the result. */
export async function fetchSource(
  spec: import('./types.js').SourceSpec,
  opts: { timeoutMs?: number; userAgent?: string } = {},
): Promise<FetchResult> {
  const cfg = config();
  const timeoutMs = opts.timeoutMs ?? cfg.fetchTimeoutMs;
  // spys.one serves the full table only to browser user agents
  const ua =
    opts.userAgent ??
    (spec.format === 'spys'
      ? 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
      : cfg.fetchUserAgent);
  try {
    const { status, body, lastModified } = await get(spec.url, 0, ua, timeoutMs, spec.auth, {
      method: spec.method,
      body: spec.body,
    });
    const ok = status >= 200 && status < 300;
    return { spec, status, body, ok, error: ok ? undefined : `HTTP ${status}`, lastModified };
  } catch (e) {
    return {
      spec,
      status: null,
      body: '',
      ok: false,
      error: (e as Error).message,
      lastModified: null,
    };
  }
}

/** Fetch all enabled sources with limited parallelism; logs a per-source report. */
export async function fetchAll(specs: import('./types.js').SourceSpec[], parallelism = 12): Promise<FetchResult[]> {
  const cfg = config();
  const enabled = specs.filter((s) => s.enabled && !cfg.disabledSources.includes(s.id));
  const results: FetchResult[] = [];
  let cursor = 0;
  const worker = async () => {
    while (cursor < enabled.length) {
      const spec = enabled[cursor]!;
      cursor++;
      const r = await fetchSource(spec);
      results.push(r);
      if (r.ok) {
        log.debug(`source ${spec.id}: ${r.body.length} bytes`);
      } else {
        log.warn(`source ${spec.id}: FAILED (${r.error})`);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(parallelism, enabled.length) }, worker));
  return results;
}
