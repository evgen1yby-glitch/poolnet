import { countryName } from './format';

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
  const rules = Array.isArray(routing.rules) ? [...routing.rules] : [];
  // DNS via the physical link avoids a dead remote DNS path; it is a known
  // beta trade-off and is documented in the release notes.
  rules.unshift({ type: 'field', port: '53,853', outboundTag: 'direct' });
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
  );
  const proxy = outbounds.find((item) => {
    const tag = String(item.tag || '').toLowerCase();
    return tag && tag !== 'direct' && tag !== 'block' && item.protocol !== 'freedom';
  }) ?? outbounds[0];
  if (!proxy || !proxy.tag) throw new Error('в конфигурации нет outbound-тега');
  const hasDirect = outbounds.some((item) => String(item.tag || '').toLowerCase() === 'direct');
  if (!hasDirect) outbounds.push({ tag: 'direct', protocol: 'freedom' });
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
    routing: buildRouting(config.routing, String(proxy.tag)),
  };
  delete clean.remarks;
  return JSON.stringify(clean);
}
