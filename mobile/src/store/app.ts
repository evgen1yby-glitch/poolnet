import { create } from 'zustand';

import { translate, type Lang } from '@/i18n';
import { logEvent } from '@/lib/diagnostics';
import { pingPresence, requestAppAccess } from '@/lib/presence';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';
import { buildXrayConfig, prefetchXrayConfig } from '@/lib/xray';
import { prepareTunnel, startTunnel, stopTunnel, tunnelStatus, tunnelSupported, verifyTunnel } from '@/lib/tunnel';

type Connection = 'disconnected' | 'connecting' | 'reconnecting' | 'connected' | 'error';

type AppState = {
  hydrated: boolean;
  subscription: StoredSubscription | null;
  country: StoredCountry | null;
  language: Lang;
  connection: Connection;
  connectionError: string | null;
  hydrate: () => Promise<void>;
  setSubscription: (value: StoredSubscription | null) => Promise<void>;
  setCountry: (value: StoredCountry | null) => Promise<void>;
  setLanguage: (value: Lang) => Promise<void>;
  connect: (options?: { recovery?: boolean }) => Promise<void>;
  recover: () => Promise<void>;
  disconnect: () => Promise<void>;
  syncTunnel: () => Promise<void>;
};

function deviceLanguage(): Lang {
  try {
    const locale = Intl.DateTimeFormat().resolvedOptions().locale.toLowerCase();
    return locale.startsWith('ru') ? 'ru' : 'en';
  } catch {
    return 'ru';
  }
}

let provisioning: Promise<StoredSubscription> | null = null;
let attemptSeq = 0;

async function provisionSubscription(language: Lang): Promise<StoredSubscription> {
  const key = await requestAppAccess();
  const subscription: StoredSubscription = {
    token: key.token,
    url: key.subscription,
    expiresAt: key.expires_at,
    unlimited: key.unlimited !== false,
  };
  await storage.setSubscription(subscription);
  return subscription;
}


const FALLBACKS: StoredCountry[] = [
  { cc: 'NL', name: 'Нидерланды', nodes: 0 },
  { cc: 'US', name: 'США', nodes: 0 },
  { cc: 'DE', name: 'Германия', nodes: 0 },
  { cc: 'FR', name: 'Франция', nodes: 0 },
];

function friendlyError(raw: string, language: Lang): string {
  if (/permission|разреш/i.test(raw)) return translate(language, 'error.permission');
  if (/доступ|access|free-status|free-challenge|free-subscription|ключ/i.test(raw)) return translate(language, 'error.access');
  if (/подписк|xray-конфиг|outbound|config/i.test(raw)) return translate(language, 'error.noConfig');
  return translate(language, 'error.tunnel');
}

export const useAppStore = create<AppState>((set, get) => ({
  hydrated: false,
  subscription: null,
  country: null,
  language: 'ru',
  connection: 'disconnected',
  connectionError: null,

  hydrate: async () => {
    const [subscription, country, language] = await Promise.all([
      storage.getSubscription(),
      storage.getCountry(),
      storage.getLanguage(),
    ]);
    const initialLanguage = language ?? deviceLanguage();
    if (!language) await storage.setLanguage(initialLanguage);
    set({ subscription, country, language: initialLanguage, hydrated: true });
    if (subscription) prefetchXrayConfig(subscription.url, country?.name);
    const status = await tunnelStatus();
    set({ connection: status.running ? 'connected' : 'disconnected', connectionError: status.error });
  },

  setSubscription: async (value) => {
    attemptSeq += 1;
    if (get().connection === 'connected' || get().connection === 'reconnecting') await stopTunnel();
    if (value) await storage.setSubscription(value);
    else await storage.clearSubscription();
    set({ subscription: value, connection: 'disconnected', connectionError: null });
  },

  setCountry: async (value) => {
    attemptSeq += 1;
    if (get().connection === 'connected') await stopTunnel();
    if (value) await storage.setCountry(value);
    else await storage.clearCountry();
    set({ country: value, connection: 'disconnected', connectionError: null });
  },

  setLanguage: async (value) => {
    await storage.setLanguage(value);
    set({ language: value });
  },

  connect: async (options) => {
    const { country, language } = get();
    if (!tunnelSupported) throw new Error(translate(language, 'error.androidOnly'));
    const attempt = ++attemptSeq;
    set({ connection: options?.recovery ? 'reconnecting' : 'connecting', connectionError: null });
    logEvent('info', 'connect', options?.recovery ? 'recovery start' : 'connect start', { country: country?.cc || 'auto' });

    try {
      // A newer tap/country change owns the tunnel. Stop the previous attempt
      // before touching the native service so two connections never overlap.
      await stopTunnel().catch(() => undefined);
      if (attempt !== attemptSeq) return;
      let subscription = get().subscription;
      if (!subscription) {
        if (!provisioning) {
          provisioning = provisionSubscription(language).finally(() => {
            provisioning = null;
          });
        }
        logEvent('info', 'access', 'provisioning');
        subscription = await provisioning;
        set({ subscription });
        logEvent('info', 'access', 'ready');
      }
      if (attempt !== attemptSeq) return;
      const granted = await prepareTunnel();
      if (attempt !== attemptSeq) return;
      if (!granted) throw new Error(translate(language, 'error.permission'));
      logEvent('info', 'vpn', 'permission granted');

      const rest = FALLBACKS.filter((candidate) => candidate.cc !== country?.cc);
      let candidates = options?.recovery
        ? [...rest, ...(country ? [country] : [])]
        : [...(country ? [country] : []), ...rest];

      // A stored free/app key from an older install can be revoked or gone.
      // Validate it before opening the VPN; rotate once if the server no
      // longer serves this subscription. No key material is shown or logged.
      try {
        await buildXrayConfig(subscription.url, candidates[0]?.name);
      } catch (error) {
        const raw = error instanceof Error ? error.message : String(error);
        if (/subscription\s+40[134]|no Xray|нет Xray|конфиг/i.test(raw)) {
          logEvent('warn', 'access', 'stored key rejected, rotating');
          const key = await requestAppAccess(true);
          subscription = {
            token: key.token,
            url: key.subscription,
            expiresAt: key.expires_at,
            unlimited: key.unlimited !== false,
          };
          await storage.setSubscription(subscription);
          set({ subscription });
          logEvent('info', 'access', 'rotated');
        }
      }
      if (attempt !== attemptSeq) return;

      let lastError: unknown = null;
      for (const candidate of candidates.slice(0, 4)) {
        if (attempt !== attemptSeq) return;
        try {
          logEvent('info', 'ax', 'candidate', { country: candidate.cc });
          const config = await buildXrayConfig(subscription.url, candidate.name);
          logEvent('info', 'ax', 'config ready', { bytes: config.length });
          await startTunnel(config);
          if (attempt !== attemptSeq) return;
          logEvent('info', 'vpn', 'service started', { country: candidate.cc });
          await new Promise((resolve) => setTimeout(resolve, options?.recovery ? 350 : 500));
          await verifyTunnel(options?.recovery ? 5000 : 6000);
          if (attempt !== attemptSeq) return;
          logEvent('info', 'vpn', 'probe ok', { country: candidate.cc });
          await get().setCountry(candidate);
          set({ connection: 'connected', connectionError: null });
          void pingPresence(true, true);
          return;
        } catch (error) {
          lastError = error;
          logEvent('warn', 'ax', 'candidate failed', { country: candidate.cc, error: error instanceof Error ? error.message : String(error) });
          if (attempt === attemptSeq) await stopTunnel().catch(() => undefined);
        }
      }
      throw lastError ?? new Error(translate(language, 'error.noNode'));
    } catch (error) {
      if (attempt !== attemptSeq) return;
      const raw = error instanceof Error ? error.message : String(error);
      if (__DEV__) console.warn('tunnel start failed', raw);
      logEvent('error', 'connect', 'failed', { error: raw });
      const friendly = friendlyError(raw, language);
      set({ connection: 'error', connectionError: friendly });
      void pingPresence(false, true);
      throw new Error(friendly);
    }
  },

  recover: async () => {
    const { connection, subscription } = get();
    if (connection !== 'connected' || !subscription) return;
    await get().connect({ recovery: true }).catch(() => undefined);
  },

  disconnect: async () => {
    attemptSeq += 1;
    logEvent('info', 'vpn', 'disconnect requested');
    await stopTunnel();
    set({ connection: 'disconnected', connectionError: null });
    void pingPresence(false, true);
  },

  syncTunnel: async () => {
    const status = await tunnelStatus();
    set({ connection: status.running ? 'connected' : 'disconnected', connectionError: status.error });
  },
}));
