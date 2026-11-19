import { asCountryConfigs } from './rotation';

const CATALOG_TTL = 30_000;
const catalogCache = new Map<string, { value: XrayConfig[]; at: number }>();

export type XrayConfig = Record<string, unknown> & {
  remarks?: string;
  outbounds?: unknown[];
  inbounds?: unknown[];
  routing?: unknown;
  route?: unknown;
};

/**
 * Fetch the Xray country catalog. The subscription returns all countries and
 * all their hosts; the client builds one-host configs from this catalog so a
 * failed host can be replaced by the next host in the same country.
 */
export async function fetchXrayCatalog(subscriptionUrl: string, fresh = false): Promise<XrayConfig[]> {
  const cached = catalogCache.get(subscriptionUrl);
  if (!fresh && cached && Date.now() - cached.at < CATALOG_TTL) return cached.value;
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
  const configs = asCountryConfigs(payload);
  if (!configs.length) throw new Error('в подписке нет Xray-конфигурации');
  catalogCache.set(subscriptionUrl, { value: configs, at: Date.now() });
  return configs;
}

export function prefetchXrayConfig(subscriptionUrl: string): void {
  void fetchXrayCatalog(subscriptionUrl).catch(() => undefined);
}
