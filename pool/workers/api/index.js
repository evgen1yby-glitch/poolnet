/**
 * open-proxy-pool edge API.
 *
 * A single Cloudflare Worker that serves the published artifacts with CORS
 * and edge caching. The data never leaves the repository: the Worker reads
 * from an origin URL (GitHub raw or jsDelivr) and only adds what a public
 * API needs — CORS headers, cache tuning and stable URLs.
 *
 * Deploy (workers/api/wrangler.toml holds name, entry and compat date):
 *   npm i -g wrangler
 *   wrangler login
 *   wrangler deploy
 *
 * The data directory is a runtime binding, not a build-time constant:
 *   wrangler secret put ORIGIN     # e.g. https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data
 *
 * Endpoints:
 *   GET /v1/check?proxy=host:port&proto=socks5   check one proxy right now
 *   GET /v1/stats      pool statistics (stats.json)
 *   GET /v1/sources    the benchmark of public lists (benchmark.json)
 *   GET /v1/benchmark  same payload as /v1/sources
 *   GET /v1/history    pool sizes and composition over time (history.json)
 *   GET /v1/proxies    full metadata (proxies.json)
 *   GET /v1/list/:proto  plain text list (all|http|socks4|socks5)
 *   GET /v1/country/:cc  country shard
 *   GET /               this index
 */

/** @typedef {{ ORIGIN: string }} Env */

const json = (data, init = {}) =>
  new Response(JSON.stringify(data), {
    ...init,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,OPTIONS',
      'access-control-max-age': '86400',
      ...init.headers,
    },
  });

const text = (data, init = {}) =>
  new Response(data, {
    ...init,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'access-control-allow-origin': '*',
      ...init.headers,
    },
  });

/** Short cache for the rapidly changing endpoints, long for stable ones. */
const CACHE = {
  live: { 'cache-control': 'public, max-age=60, s-maxage=300', 'cdn-cache-control': 'public, max-age=300' },
  warm: { 'cache-control': 'public, max-age=300, s-maxage=3600', 'cdn-cache-control': 'public, max-age=3600' },
  cold: { 'cache-control': 'public, max-age=3600, s-maxage=86400', 'cdn-cache-control': 'public, max-age=86400' },
};

const ROUTES = [
  { match: /^\/v1\/stats\/?$/, file: () => 'stats.json', kind: 'json', cache: 'live' },
  { match: /^\/v1\/sources\/?$/, file: () => 'benchmark.json', kind: 'json', cache: 'live' },
  { match: /^\/v1\/history\/?$/, file: () => 'history.json', kind: 'json', cache: 'warm' },
  { match: /^\/v1\/proxies\/?$/, file: () => 'proxies.json', kind: 'json', cache: 'live' },
  { match: /^\/v1\/benchmark\/?$/, file: () => 'benchmark.json', kind: 'json', cache: 'live' },
  {
    match: /^\/v1\/list\/(all|http|socks4|socks5)\/?$/,
    file: (m) => (m[1] === 'all' ? 'all.txt' : `${m[1]}.txt`),
    kind: 'text',
    cache: 'live',
  },
  { match: /^\/v1\/list\/?$/, file: () => 'all.txt', kind: 'text', cache: 'live' },
  {
    match: /^\/v1\/country\/([A-Za-z]{2})\/?$/,
    file: (m) => `country/${m[1].toUpperCase()}.txt`,
    kind: 'text',
    cache: 'warm',
  },
];

const INDEX = {
  service: 'open-proxy-pool',
  endpoints: [
    '/v1/check?proxy=host:port&proto=socks5',
    '/v1/stats',
    '/v1/sources',
    '/v1/benchmark',
    '/v1/history',
    '/v1/proxies',
    '/v1/list/:proto',
    '/v1/country/:cc',
  ],
  notes:
    'Data is republished every 15 minutes; responses may be cached at the edge. These are public proxies run by third parties.',
};

const PROTOCOLS = ['http', 'socks4', 'socks5'];

/** a check result describes this moment, nothing may cache it */
const NO_STORE = { 'cache-control': 'no-store', 'access-control-allow-origin': '*' };

/** On-demand single-proxy check: the same contract as the platform's page. */
async function handleCheck(url) {
  const target = parseProxyParam(url.searchParams.get('proxy') ?? '', url.searchParams.get('proto') ?? 'socks5');
  if ('error' in target) {
    return json({ error: target.error }, { status: 400, headers: NO_STORE });
  }
  let connect;
  try {
    // workerd only: Node tests import check.js directly with a stub socket
    ({ connect } = await import('cloudflare:sockets'));
  } catch {
    return json({ error: 'sockets unavailable outside a worker runtime' }, { status: 501, headers: NO_STORE });
  }
  const { checkProxyOnDemand } = await import('./check.js');
  const outcome = await checkProxyOnDemand({ proxy: target.proxy, connect, targetUrl: 'http://httpbingo.org/get' });
  return json(
    { proxy: `${target.proxy.protocol}://${target.proxy.host}:${target.proxy.port}`, ...outcome },
    {
      headers: { 'cache-control': 'no-store', 'access-control-allow-origin': '*' },
    },
  );
}

/** host:port plus a protocol; only routable addresses are accepted. */
function parseProxyParam(raw, protoRaw) {
  const m = /^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$/.exec(raw.trim());
  if (!m) return { error: 'expected proxy=host:port' };
  const port = Number(m[2]);
  if (!(port > 0 && port <= 65535)) return { error: 'port out of range' };
  const protocol = protoRaw.toLowerCase();
  if (!PROTOCOLS.includes(protocol)) return { error: `proto must be one of ${PROTOCOLS.join(', ')}` };
  const octets = m[1].split('.').map(Number);
  const [a, b] = octets;
  const reserved =
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    a >= 224;
  if (reserved) return { error: 'address is not routable' };
  return { proxy: { protocol, host: m[1], port } };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== 'GET' && request.method !== 'OPTIONS') {
      return json({ error: 'method not allowed', method: request.method }, { status: 405 });
    }
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET,OPTIONS',
          'access-control-max-age': '86400',
        },
      });
    }
    if (url.pathname === '/' || url.pathname === '/v1' || url.pathname === '/v1/') {
      return json(INDEX, { headers: CACHE.cold });
    }
    if (url.pathname === '/v1/check') {
      return handleCheck(url);
    }

    for (const route of ROUTES) {
      const m = url.pathname.match(route.match);
      if (!m) continue;
      try {
        if (!env.ORIGIN) {
          return json({ error: 'ORIGIN binding missing', hint: 'wrangler secret put ORIGIN' }, { status: 502 });
        }
        const origin = env.ORIGIN.replace(/\/$/, '') + '/' + route.file(m);
        const upstream = await fetch(origin, {
          headers: { accept: route.kind === 'json' ? 'application/json' : 'text/plain' },
        });
        if (!upstream.ok) {
          return json(
            { error: 'upstream', status: upstream.status, path: url.pathname },
            { status: upstream.status === 404 ? 404 : 502 },
          );
        }
        const body = await upstream.text();
        return route.kind === 'json'
          ? json(JSON.parse(body), { headers: CACHE[route.cache] })
          : text(body, { headers: CACHE[route.cache] });
      } catch (e) {
        return json({ error: 'origin fetch failed', detail: e && e.message ? e.message : String(e) }, { status: 502 });
      }
    }
    return json({ error: 'not found', endpoints: INDEX.endpoints }, { status: 404 });
  },
};
