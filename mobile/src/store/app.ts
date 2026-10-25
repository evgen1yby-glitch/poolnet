import { create } from 'zustand';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';
import { buildXrayConfig } from '@/lib/xray';
import { prepareTunnel, startTunnel, stopTunnel, tunnelStatus, tunnelSupported } from '@/lib/tunnel';

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
      const config = await buildXrayConfig(subscription.url, country?.name);
      await startTunnel(config);
      set({ connection: 'connected', connectionError: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось подключиться';
      set({ connection: 'error', connectionError: message });
      throw error;
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
