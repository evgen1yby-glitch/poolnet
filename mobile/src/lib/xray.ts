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
  const outbounds = config.outbounds as Record<string, unknown>[];
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
    // PoolNet's server config uses a least-ping balancer. Xray Core's mobile
    // build can report an empty balancer before observatory data exists, which
    // leaves every packet on the direct path. Pin the first node in this
    // country instead; the UI already represents one selected country.
    routing: {
      domainStrategy: 'AsIs',
      rules: [
        { type: 'field', port: '53,853', outboundTag: 'direct' },
        { type: 'field', ip: ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '169.254.0.0/16', '100.64.0.0/10', '::1/128', 'fc00::/7', 'fe80::/10'], outboundTag: 'direct' },
        { type: 'field', network: 'tcp,udp', outboundTag: String(proxy.tag) },
      ],
    },
  };
  delete clean.remarks;
  return JSON.stringify(clean);
}
