import { Platform } from 'react-native';

export type SupportOfferKind = 'ad' | 'partner' | 'offerwall';

export type SupportOffer = {
  id: string;
  kind: SupportOfferKind;
  title: string;
  body: string;
  cta: string;
  url: string;
  badge?: string;
};

export type SupportConfig = {
  offers: SupportOffer[];
  donateUrl?: string | null;
  contactUrl?: string | null;
};

const SUPPORT_URL = 'https://poolnet.online/app/support.json';
const MAX_OFFERS = 5;

function isHttps(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

function validate(value: unknown): SupportConfig {
  if (!value || typeof value !== 'object') throw new Error('invalid support config');
  const raw = value as Record<string, unknown>;
  const source = Array.isArray(raw.offers) ? raw.offers : [];
  const offers = source
    .slice(0, MAX_OFFERS)
    .map((item, index): SupportOffer | null => {
      if (!item || typeof item !== 'object') return null;
      const offer = item as Record<string, unknown>;
      if (!isHttps(offer.url)) return null;
      const kind: SupportOfferKind =
        offer.kind === 'ad' || offer.kind === 'offerwall' ? offer.kind : 'partner';
      return {
        id: typeof offer.id === 'string' && offer.id ? offer.id.slice(0, 60) : `offer-${index}`,
        kind,
        title: typeof offer.title === 'string' ? offer.title.slice(0, 80) : '',
        body: typeof offer.body === 'string' ? offer.body.slice(0, 220) : '',
        cta: typeof offer.cta === 'string' ? offer.cta.slice(0, 30) : 'Open',
        url: offer.url,
        badge: typeof offer.badge === 'string' ? offer.badge.slice(0, 24) : undefined,
      };
    })
    .filter((offer): offer is SupportOffer => Boolean(offer && offer.title));
  return {
    offers,
    donateUrl: isHttps(raw.donateUrl) ? raw.donateUrl : null,
    contactUrl: isHttps(raw.contactUrl) ? raw.contactUrl : null,
  };
}

export async function fetchSupportConfig(): Promise<SupportConfig> {
  if (Platform.OS === 'web') return { offers: [], donateUrl: null, contactUrl: null };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(`${SUPPORT_URL}?t=${Date.now()}`, {
      cache: 'no-store',
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`support ${response.status}`);
    return validate(await response.json());
  } finally {
    clearTimeout(timer);
  }
}
