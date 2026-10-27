import { countryName } from './format';

const CONFIG_TTL = 60_000;
const configCache = new Map<string, { value: string; at: number }>();

export type XrayConfig = Record<string, unknown> & {
  remarks?: string;
  outbounds?: unknown[];
  inbounds?: unknown[];
  routing?: unknown;
  route?: unknown;
};

function asConfigs(payload: unknown): XrayConfig[] {
  if (Array.isArray(payload)) return payload.filter((item): item is XrayConfig => Boolean(item && typeof item === 'object'));
  if (payload && typeof payload === 'object') return [payload as XrayConfig];
  return [];
}

type Routing = Record<string, unknown> & {
  rules?: Record<string, unknown>[];
  balancers?: Record<string, unknown>[];
};

function buildRouting(source: unknown, fallbackTag: string): Routing {
  const routing = (source && typeof source === 'object' ? { ...(source as Routing) } : {}) as Routing;
  const sourceRules = Array.isArray(routing.rules) ? [...routing.rules] : [];
  const isDirect = (rule: Record<string, unknown>) => rule.outboundTag === 'direct';
  const rules = sourceRules.filter((rule) => {
    const port = String(rule.port ?? '');
    // DNS must travel through the tunnel. A direct 1.1.1.1 lookup dies on
    // networks that block public resolvers, taking every candidate with it.
    if (isDirect(rule) && /(^|,)53(,|$)/.test(port)) return false;
    // Drop a bare direct catch-all; the proxy rule below must win.
    if (isDirect(rule) && !rule.ip && !rule.domain && !rule.port) return false;
    return true;
  });
  const balancers = Array.isArray(routing.balancers) ? routing.balancers : [];
  if (balancers.length) {
    routing.balancers = balancers.map((balancer) => ({
      ...balancer,
      fallbackTag: (balancer.fallbackTag as string | undefined) || fallbackTag,
    }));
    routing.rules = rules;
  } else {
    routing.rules = [
      { type: 'field', ip: ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '169.254.0.0/16', '100.64.0.0/10'], outboundTag: 'direct' },
      ...rules,
      { type: 'field', network: 'tcp,udp', outboundTag: fallbackTag },
    ];
  }
  return routing;
}

/**
 * Build a TUN config from the same Xray payload the website hands out.
 * The server returns one config per country; choose the selected country by
 * its human-readable `remarks`, otherwise fall back to the first.
 */
export async function buildXrayConfig(subscriptionUrl: string, country?: string | null): Promise<string> {
  const cacheKey = `${subscriptionUrl}|${country ?? ''}`;
  const cached = configCache.get(cacheKey);
  if (cached && Date.now() - cached.at < CONFIG_TTL) return cached.value;
  const url = `${subscriptionUrl}${subscriptionUrl.includes('?') ? '&' : '?'}core=xray`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  let payload: unknown;
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`subscription ${response.status}`);
    payload = await response.json();
  } finally {
    clearTimeout(timer);
  }
  const configs = asConfigs(payload);
  const label = country ? (country.length === 2 ? countryName(country) : country) : 'Нидерланды';
  const config = configs.find((item) => String(item.remarks || '').includes(label)) ?? configs[0];
  if (!config || !Array.isArray(config.outbounds) || config.outbounds.length === 0) {
    throw new Error('в подписке нет Xray-конфигурации');
  }
  const outbounds = (config.outbounds as Record<string, unknown>[]).map((item) =>
    item.type === 'urltest'
      ? { ...item, interval: '15s', interrupt_exist_connections: true }
      : item,
  ).filter((item) => {
    // Older libXray builds reject plain VLESS without TLS/Reality. Do not let
    // one bad pool node invalidate the whole country config.
    if (item.protocol !== 'vless') return true;
    const stream = item.streamSettings as Record<string, unknown> | undefined;
    const security = String(stream?.security ?? 'none');
    if (security === 'tls' || security === 'reality') return true;
    const settings = item.settings as Record<string, unknown> | undefined;
    const vnext = Array.isArray(settings?.vnext) ? settings.vnext as Record<string, unknown>[] : [];
    const users = vnext.flatMap((entry) => Array.isArray(entry.users) ? entry.users as Record<string, unknown>[] : []);
    return users.some((user) => user.encryption && user.encryption !== 'none');
  });
  if (!outbounds.some((item) => item.protocol && item.protocol !== 'freedom' && item.protocol !== 'blackhole')) {
    throw new Error('в подписке нет рабочей Xray-конфигурации');
  }
  const proxy = outbounds.find((item) => {
    const tag = String(item.tag || '').toLowerCase();
    return tag && tag !== 'direct' && tag !== 'block' && item.protocol !== 'freedom';
  }) ?? outbounds[0];
  if (!proxy || !proxy.tag) throw new Error('в конфигурации нет outbound-тега');
  const hasDirect = outbounds.some((item) => String(item.tag || '').toLowerCase() === 'direct');
  if (!hasDirect) outbounds.push({ tag: 'direct', protocol: 'freedom' });
  // Pool ordering puts the freshest/healthiest nodes at the end. Use the last
  // proxy as the immediate fallback; the observatory can still move later.
  const fallback = [...outbounds].reverse().find((item) => {
    const tag = String(item.tag || '').toLowerCase();
    return tag && tag !== 'direct' && tag !== 'block' && item.protocol !== 'freedom';
  }) ?? proxy;
  const clean: XrayConfig = {
    ...config,
    inbounds: [
      {
        tag: 'tun-in',
        protocol: 'tun',
        settings: { name: 'poolnet-tun', mtu: 1500 },
        sniffing: { enabled: true, destOverride: ['http', 'tls', 'quic'] },
      },
    ],
    // Keep the server's least-ping balancer, but give it a fallback. Before
    // the observatory produces its first sample Xray returns an empty tag;
    // without `fallbackTag` that left the whole tunnel on the direct path.
    // DNS stays direct for reliability; other traffic goes through the balancer.
    routing: buildRouting(config.routing, String(fallback.tag)),
  };
  delete clean.remarks;
  const result = JSON.stringify(clean);
  configCache.set(cacheKey, { value: result, at: Date.now() });
  return result;
}

export function prefetchXrayConfig(subscriptionUrl: string, country?: string | null): void {
  void buildXrayConfig(subscriptionUrl, country).catch(() => undefined);
}
