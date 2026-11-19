import { countryName } from './format';
import type { XrayConfig } from './xray';

export type CountryPreference = { cc: string; name: string };

export type RotationCandidate = {
  key: string;
  countryCc: string;
  countryName: string;
  hostTag: string;
  hostIndex: number;
  hostTotal: number;
  config: string;
  fallback: boolean;
};

const MAX_HOSTS_SELECTED = 8;
const MAX_HOSTS_FALLBACK = 2;
const MAX_TOTAL_ATTEMPTS = 10;
const PRIVATE_NETWORKS = [
  '10.0.0.0/8',
  '172.16.0.0/12',
  '192.168.0.0/16',
  '127.0.0.0/8',
  '169.254.0.0/16',
  '100.64.0.0/10',
];

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function asCountryConfigs(payload: unknown): XrayConfig[] {
  if (Array.isArray(payload)) {
    return payload.filter((item): item is XrayConfig => Boolean(item && typeof item === 'object'));
  }
  if (payload && typeof payload === 'object') return [payload as XrayConfig];
  return [];
}

function normalizeName(value: string): string {
  return value.toLocaleLowerCase('ru-RU').replace(/\s+\d+\s*$/, '').trim();
}

function namesFor(preference: CountryPreference): string[] {
  return Array.from(
    new Set(
      [preference.name, countryName(preference.cc, 'ru'), countryName(preference.cc, 'en')]
        .filter(Boolean)
        .map(normalizeName),
    ),
  );
}

function findCountry(configs: XrayConfig[], preference: CountryPreference): XrayConfig | null {
  const names = namesFor(preference);
  return (
    configs.find((config) => {
      const remarks = normalizeName(String(config.remarks ?? ''));
      return names.some((name) => remarks.includes(name));
    }) ?? null
  );
}

function outboundEndpoint(outbound: Record<string, unknown>): { address: string | null; port: number | null } {
  const settings = asRecord(outbound.settings);
  if (!settings) return { address: null, port: null };
  const vnext = asRecord(asArray(settings.vnext)[0]);
  if (vnext) {
    return {
      address: typeof vnext.address === 'string' ? vnext.address : null,
      port: Number.isInteger(vnext.port) ? Number(vnext.port) : null,
    };
  }
  const server = asRecord(asArray(settings.servers)[0]);
  if (server) {
    return {
      address: typeof server.address === 'string' ? server.address : null,
      port: Number.isInteger(server.port) ? Number(server.port) : null,
    };
  }
  return { address: null, port: null };
}

function usableProxy(outbound: Record<string, unknown>): boolean {
  const tag = String(outbound.tag ?? '').toLowerCase();
  const protocol = String(outbound.protocol ?? '').toLowerCase();
  if (!tag || tag === 'direct' || tag === 'block') return false;
  if (!protocol || protocol === 'freedom' || protocol === 'blackhole') return false;
  if (protocol !== 'vless') return true;
  const stream = asRecord(outbound.streamSettings);
  const security = String(stream?.security ?? 'none');
  if (security === 'tls' || security === 'reality') return true;
  const settings = asRecord(outbound.settings);
  const users = asArray(settings?.vnext)
    .map(asRecord)
    .flatMap((entry) => asArray(entry?.users).map(asRecord))
    .filter((user): user is Record<string, unknown> => Boolean(user));
  return users.some((user) => Boolean(user.encryption) && user.encryption !== 'none');
}

function hostCandidates(config: XrayConfig, preference: CountryPreference, fallback: boolean): RotationCandidate[] {
  const outbounds = asArray(config.outbounds)
    .map(asRecord)
    .filter((outbound): outbound is Record<string, unknown> => Boolean(outbound))
    .filter(usableProxy);
  const limited = outbounds.slice(0, fallback ? MAX_HOSTS_FALLBACK : MAX_HOSTS_SELECTED);
  return limited.map((outbound, index): RotationCandidate => {
    const hostTag = String(outbound.tag);
    const endpoint = outboundEndpoint(outbound);
    return {
      key: `${preference.cc}|${String(outbound.protocol)}|${endpoint.address ?? hostTag}|${endpoint.port ?? 0}`,
      countryCc: preference.cc,
      countryName: preference.name,
      hostTag,
      hostIndex: index + 1,
      hostTotal: limited.length,
      config: buildSingleHostConfig(config, outbound),
      fallback,
    };
  });
}

export function buildSingleHostConfig(country: XrayConfig, outbound: Record<string, unknown>): string {
  const tag = String(outbound.tag);
  if (!tag) throw new Error('outbound tag missing');
  const sourceOutbounds = asArray(country.outbounds)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => Boolean(item));
  const direct =
    sourceOutbounds.find((item) => String(item.tag ?? '').toLowerCase() === 'direct') ??
    { tag: 'direct', protocol: 'freedom' };
  const block =
    sourceOutbounds.find((item) => String(item.tag ?? '').toLowerCase() === 'block') ??
    { tag: 'block', protocol: 'blackhole' };
  const routing = asRecord(country.routing) ?? {};
  const sourceRules = asArray(routing.rules)
    .map(asRecord)
    .filter((rule): rule is Record<string, unknown> => Boolean(rule));
  const directRules = sourceRules.filter(
    (rule) => rule.outboundTag === 'direct' && Boolean(rule.ip || rule.domain || rule.port),
  );
  const clean = {
    ...country,
    outbounds: [outbound, direct, block],
    inbounds: [
      {
        tag: 'tun-in',
        protocol: 'tun',
        settings: { name: 'poolnet-tun', mtu: 1500 },
        sniffing: { enabled: true, destOverride: ['http', 'tls', 'quic'] },
      },
    ],
    routing: {
      domainStrategy: routing.domainStrategy ?? 'AsIs',
      rules: [
        { type: 'field', ip: PRIVATE_NETWORKS, outboundTag: 'direct' },
        ...directRules,
        { type: 'field', network: 'tcp,udp', outboundTag: tag },
      ],
    },
  } as XrayConfig;
  delete clean.observatory;
  delete clean.remarks;
  return JSON.stringify(clean);
}

export function buildRotationPlan(
  configs: XrayConfig[],
  preferred: CountryPreference,
  fallbacks: CountryPreference[],
): RotationCandidate[] {
  const selectedConfig = findCountry(configs, preferred);
  const plan: RotationCandidate[] = [];
  const seen = new Set<string>();
  const add = (config: XrayConfig | null, preference: CountryPreference, fallback: boolean) => {
    if (!config) return;
    for (const candidate of hostCandidates(config, preference, fallback)) {
      if (plan.length >= MAX_TOTAL_ATTEMPTS) return;
      if (seen.has(candidate.key)) continue;
      seen.add(candidate.key);
      plan.push(candidate);
    }
  };

  add(selectedConfig, preferred, false);
  for (const fallback of fallbacks) {
    if (fallback.cc === preferred.cc) continue;
    add(findCountry(configs, fallback), fallback, true);
  }
  return plan;
}
