import { create } from 'zustand';

import { translate, type Lang } from '@/i18n';
import { logEvent } from '@/lib/diagnostics';
import { pingPresence, requestAppAccess } from '@/lib/presence';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';
import { buildRotationPlan } from '@/lib/rotation';
import { fetchXrayCatalog, prefetchXrayConfig } from '@/lib/xray';
import { fetchExitIp, prepareTunnel, startTunnel, stopTunnel, tunnelStatus, tunnelSupported, verifyTunnel } from '@/lib/tunnel';

type Connection = 'disconnected' | 'connecting' | 'reconnecting' | 'connected' | 'error';

type AppState = {
  hydrated: boolean;
  subscription: StoredSubscription | null;
  country: StoredCountry | null;
  language: Lang;
  connection: Connection;
  connectionError: string | null;
  sessionStartedAt: number | null;
  rxBytes: number;
  txBytes: number;
  exitIp: string | null;
  activeCountry: StoredCountry | null;
  rotation: {
    attempt: number;
    total: number;
    countryCc: string;
    countryName: string;
    hostIndex: number;
    hostTotal: number;
    fallback: boolean;
  } | null;
  hydrate: () => Promise<void>;
  setSubscription: (value: StoredSubscription | null) => Promise<void>;
  setCountry: (value: StoredCountry | null) => Promise<void>;
  setLanguage: (value: Lang) => Promise<void>;
  connect: (options?: { recovery?: boolean }) => Promise<void>;
  recover: () => Promise<void>;
  disconnect: () => Promise<void>;
  syncTunnel: () => Promise<void>;
  refreshExitIp: () => Promise<void>;
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
  sessionStartedAt: null,
  rxBytes: 0,
  txBytes: 0,
  exitIp: null,
  activeCountry: null,
  rotation: null,

  hydrate: async () => {
    const [subscription, country, language] = await Promise.all([
      storage.getSubscription(),
      storage.getCountry(),
      storage.getLanguage(),
    ]);
    const initialLanguage = language ?? deviceLanguage();
    if (!language) await storage.setLanguage(initialLanguage);
    set({ subscription, country, language: initialLanguage, hydrated: true });
    if (subscription) prefetchXrayConfig(subscription.url);
    const status = await tunnelStatus();
    set({
      connection: status.running ? 'connected' : 'disconnected',
      connectionError: status.error,
      sessionStartedAt: status.running ? status.startedAt || Date.now() : null,
      rxBytes: status.running ? status.rxBytes : 0,
      txBytes: status.running ? status.txBytes : 0,
      activeCountry: status.running ? country : null,
      rotation: null,
    });
    if (status.running) void get().refreshExitIp();
  },

  setSubscription: async (value) => {
    attemptSeq += 1;
    if (get().connection !== 'disconnected') await stopTunnel();
    if (value) await storage.setSubscription(value);
    else await storage.clearSubscription();
    set({
      subscription: value,
      connection: 'disconnected',
      connectionError: null,
      sessionStartedAt: null,
      rxBytes: 0,
      txBytes: 0,
      exitIp: null,
      activeCountry: null,
      rotation: null,
    });
  },

  setCountry: async (value) => {
    attemptSeq += 1;
    if (get().connection !== 'disconnected') await stopTunnel();
    if (value) await storage.setCountry(value);
    else await storage.clearCountry();
    set({
      country: value,
      connection: 'disconnected',
      connectionError: null,
      sessionStartedAt: null,
      rxBytes: 0,
      txBytes: 0,
      exitIp: null,
      activeCountry: null,
      rotation: null,
    });
  },

  setLanguage: async (value) => {
    await storage.setLanguage(value);
    set({ language: value });
  },

  connect: async (options) => {
    const { country, language } = get();
    if (!tunnelSupported) throw new Error(translate(language, 'error.androidOnly'));
    const attempt = ++attemptSeq;
    set({
      connection: options?.recovery ? 'reconnecting' : 'connecting',
      connectionError: null,
      sessionStartedAt: null,
      rxBytes: 0,
      txBytes: 0,
      exitIp: null,
      activeCountry: null,
      rotation: null,
    });
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

      const preferred = options?.recovery
        ? (get().activeCountry ?? country ?? FALLBACKS[0])
        : (country ?? FALLBACKS[0]);

      // One catalog fetch gives us every host in every country. The client
      // then tries one host at a time, best-ranked first, before leaving the
      // selected country. A bad host no longer invalidates the country.
      let catalog;
      try {
        catalog = await fetchXrayCatalog(subscription.url);
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
          catalog = await fetchXrayCatalog(subscription.url, true);
          logEvent('info', 'access', 'rotated');
        } else {
          throw error;
        }
      }
      if (attempt !== attemptSeq) return;

      const plan = buildRotationPlan(catalog, preferred, FALLBACKS);
      if (!plan.length) throw new Error(translate(language, 'error.noNode'));

      let lastError: unknown = null;
      for (let index = 0; index < plan.length; index += 1) {
        const candidate = plan[index];
        if (attempt !== attemptSeq) {
          await stopTunnel().catch(() => undefined);
          return;
        }
        set({
          rotation: {
            attempt: index + 1,
            total: plan.length,
            countryCc: candidate.countryCc,
            countryName: candidate.countryName,
            hostIndex: candidate.hostIndex,
            hostTotal: candidate.hostTotal,
            fallback: candidate.fallback,
          },
        });
        try {
          logEvent('info', 'ax', 'candidate', {
            country: candidate.countryCc,
            host: candidate.hostTag,
            hostIndex: candidate.hostIndex,
            hostTotal: candidate.hostTotal,
            fallback: candidate.fallback,
          });
          await startTunnel(candidate.config);
          if (attempt !== attemptSeq) {
            await stopTunnel().catch(() => undefined);
            return;
          }
          logEvent('info', 'vpn', 'service started', { country: candidate.countryCc, host: candidate.hostTag });
          await new Promise((resolve) => setTimeout(resolve, index === 0 ? 450 : 250));
          const exitIp = await verifyTunnel(index < 2 ? 6000 : 4500);
          if (attempt !== attemptSeq) {
            await stopTunnel().catch(() => undefined);
            return;
          }
          logEvent('info', 'vpn', 'probe ok', { country: candidate.countryCc, host: candidate.hostTag });
          const activeCountry = {
            cc: candidate.countryCc,
            name: candidate.countryName,
            nodes: candidate.hostTotal,
          };
          // If a specific country was chosen but the connection landed on a
          // fallback country, that country is now the real selection. Auto
          // stays Auto; it must not become pinned to a lucky fallback.
          const adoptedCountry = country && country.cc !== candidate.countryCc ? activeCountry : country;
          if (adoptedCountry && adoptedCountry !== country) {
            await storage.setCountry(adoptedCountry).catch(() => undefined);
            if (attempt !== attemptSeq) {
              await stopTunnel().catch(() => undefined);
              return;
            }
          }
          set({
            country: adoptedCountry,
            connection: 'connected',
            connectionError: null,
            sessionStartedAt: Date.now(),
            rxBytes: 0,
            txBytes: 0,
            exitIp,
            activeCountry,
            rotation: null,
          });
          void get().syncTunnel();
          void pingPresence(true, true);
          return;
        } catch (error) {
          lastError = error;
          logEvent('warn', 'ax', 'candidate failed', {
            country: candidate.countryCc,
            host: candidate.hostTag,
            error: error instanceof Error ? error.message : String(error),
          });
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
      set({
        connection: 'error',
        connectionError: friendly,
        sessionStartedAt: null,
        rxBytes: 0,
        txBytes: 0,
        exitIp: null,
        activeCountry: null,
        rotation: null,
      });
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
    set({
      connection: 'disconnected',
      connectionError: null,
      sessionStartedAt: null,
      rxBytes: 0,
      txBytes: 0,
      exitIp: null,
      activeCountry: null,
      rotation: null,
    });
    void pingPresence(false, true);
  },

  syncTunnel: async () => {
    const status = await tunnelStatus();
    if (!status.running) {
      const connection = get().connection;
      if (connection === 'connecting' || connection === 'reconnecting') return;
      set({
        connection: 'disconnected',
        connectionError: status.error,
        sessionStartedAt: null,
        rxBytes: 0,
        txBytes: 0,
        exitIp: null,
        activeCountry: null,
        rotation: null,
      });
      return;
    }
    set({
      connection: 'connected',
      connectionError: status.error,
      sessionStartedAt: status.startedAt || get().sessionStartedAt || Date.now(),
      rxBytes: status.rxBytes,
      txBytes: status.txBytes,
      activeCountry: get().activeCountry,
    });
  },

  refreshExitIp: async () => {
    if (get().connection !== 'connected') return;
    try {
      const ip = await fetchExitIp();
      if (get().connection === 'connected') set({ exitIp: ip });
    } catch {
      // The tunnel is up even if the public-IP probe is unavailable.
    }
  },
}));
