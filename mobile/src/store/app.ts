import { create } from 'zustand';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';
import { buildXrayConfig } from '@/lib/xray';
import { prepareTunnel, startTunnel, stopTunnel, tunnelStatus, tunnelSupported, verifyTunnel } from '@/lib/tunnel';

type AppState = {
  hydrated: boolean;
  subscription: StoredSubscription | null;
  country: StoredCountry | null;
  connection: 'disconnected' | 'connecting' | 'connected' | 'error';
  connectionError: string | null;
  hydrate: () => Promise<void>;
  setSubscription: (value: StoredSubscription | null) => Promise<void>;
  setCountry: (value: StoredCountry) => Promise<void>;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  syncTunnel: () => Promise<void>;
};

export const useAppStore = create<AppState>((set, get) => ({
  hydrated: false,
  subscription: null,
  country: null,
  connection: 'disconnected',
  connectionError: null,
  hydrate: async () => {
    const [subscription, country] = await Promise.all([
      storage.getSubscription(),
      storage.getCountry(),
    ]);
    set({ subscription, country, hydrated: true });
    const status = await tunnelStatus();
    set({ connection: status.running ? 'connected' : 'disconnected', connectionError: status.error });
  },
  setSubscription: async (value) => {
    if (get().connection === 'connected') await stopTunnel();
    if (value) await storage.setSubscription(value);
    else await storage.clearSubscription();
    set({ subscription: value, connection: 'disconnected', connectionError: null });
  },
  setCountry: async (value) => {
    if (get().connection === 'connected') await stopTunnel();
    await storage.setCountry(value);
    set({ country: value, connection: 'disconnected', connectionError: null });
  },
  connect: async () => {
    const { subscription, country } = get();
    if (!subscription) throw new Error('Сначала получите ключ');
    if (!tunnelSupported) throw new Error('VPN-туннель доступен только в Android-сборке');
    set({ connection: 'connecting', connectionError: null });
    try {
      const granted = await prepareTunnel();
      if (!granted) throw new Error('Разрешение VPN не выдано');
      const fallbacks = ['Нидерланды', 'США', 'Германия'];
      const candidates = [
        ...(country ? [country] : []),
        ...fallbacks
          .filter((name) => name !== country?.name)
          .map((name) => ({ cc: name === 'США' ? 'US' : name === 'Германия' ? 'DE' : 'NL', name, nodes: 0 })),
      ];
      let lastError: unknown = null;
      for (const candidate of candidates.slice(0, 3)) {
        try {
          const config = await buildXrayConfig(subscription.url, candidate.name);
          await startTunnel(config);
          await new Promise((resolve) => setTimeout(resolve, 900));
          await verifyTunnel();
          await get().setCountry(candidate);
          set({ connection: 'connected', connectionError: null });
          return;
        } catch (error) {
          lastError = error;
          await stopTunnel().catch(() => undefined);
        }
      }
      throw lastError ?? new Error('Нет доступного узла');
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error);
      if (__DEV__) console.warn('tunnel start failed', raw);
      const friendly = /permission|разреш/i.test(raw)
        ? 'Разрешение VPN не выдано.'
        : /подписк|xray-конфиг|outbound/i.test(raw)
          ? 'В подписке нет рабочей Xray-конфигурации. Выберите другую страну.'
          : 'Не удалось поднять туннель. Проверьте соединение или выберите другой узел.';
      set({ connection: 'error', connectionError: friendly });
      throw new Error(friendly);
    }
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
