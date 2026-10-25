import { create } from 'zustand';

import { translate, type Lang } from '@/i18n';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';
import { buildXrayConfig } from '@/lib/xray';
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

const FALLBACKS: StoredCountry[] = [
  { cc: 'NL', name: 'Нидерланды', nodes: 0 },
  { cc: 'US', name: 'США', nodes: 0 },
  { cc: 'DE', name: 'Германия', nodes: 0 },
];

function friendlyError(raw: string, language: Lang): string {
  if (/permission|разреш/i.test(raw)) return translate(language, 'error.permission');
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
    const status = await tunnelStatus();
    set({ connection: status.running ? 'connected' : 'disconnected', connectionError: status.error });
  },

  setSubscription: async (value) => {
    if (get().connection === 'connected' || get().connection === 'reconnecting') await stopTunnel();
    if (value) await storage.setSubscription(value);
    else await storage.clearSubscription();
    set({ subscription: value, connection: 'disconnected', connectionError: null });
  },

  setCountry: async (value) => {
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
    const { subscription, country, language } = get();
    if (!subscription) throw new Error(translate(language, 'error.keyFirst'));
    if (!tunnelSupported) throw new Error(translate(language, 'error.androidOnly'));
    set({ connection: options?.recovery ? 'reconnecting' : 'connecting', connectionError: null });

    try {
      const granted = await prepareTunnel();
      if (!granted) throw new Error(translate(language, 'error.permission'));

      const rest = FALLBACKS.filter((candidate) => candidate.cc !== country?.cc);
      const candidates = options?.recovery
        ? [...rest, ...(country ? [country] : [])]
        : [...(country ? [country] : []), ...rest];

      let lastError: unknown = null;
      for (const candidate of candidates.slice(0, 3)) {
        try {
          const config = await buildXrayConfig(subscription.url, candidate.name);
          await startTunnel(config);
          await new Promise((resolve) => setTimeout(resolve, options?.recovery ? 600 : 900));
          await verifyTunnel(options?.recovery ? 4500 : 8000);
          await get().setCountry(candidate);
          set({ connection: 'connected', connectionError: null });
          return;
        } catch (error) {
          lastError = error;
          await stopTunnel().catch(() => undefined);
        }
      }
      throw lastError ?? new Error(translate(language, 'error.noNode'));
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error);
      if (__DEV__) console.warn('tunnel start failed', raw);
      const friendly = friendlyError(raw, language);
      set({ connection: 'error', connectionError: friendly });
      throw new Error(friendly);
    }
  },

  recover: async () => {
    const { connection, subscription } = get();
    if (connection !== 'connected' || !subscription) return;
    await get().connect({ recovery: true }).catch(() => undefined);
  },

  disconnect: async () => {
    await stopTunnel();
    set({ connection: 'disconnected', connectionError: null });
  },

  syncTunnel: async () => {
    const status = await tunnelStatus();
    set({ connection: status.running ? 'connected' : 'disconnected', connectionError: status.error });
  },
}));
