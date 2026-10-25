import { create } from 'zustand';
import { storage, type StoredCountry, type StoredSubscription } from '@/lib/storage';

type AppState = {
  hydrated: boolean;
  subscription: StoredSubscription | null;
  country: StoredCountry | null;
  hydrate: () => Promise<void>;
  setSubscription: (value: StoredSubscription | null) => Promise<void>;
  setCountry: (value: StoredCountry) => Promise<void>;
};

export const useAppStore = create<AppState>((set) => ({
  hydrated: false,
  subscription: null,
  country: null,
  hydrate: async () => {
    const [subscription, country] = await Promise.all([
      storage.getSubscription(),
      storage.getCountry(),
    ]);
    set({ subscription, country, hydrated: true });
  },
  setSubscription: async (value) => {
    if (value) await storage.setSubscription(value);
    else await storage.clearSubscription();
    set({ subscription: value });
  },
  setCountry: async (value) => {
    await storage.setCountry(value);
    set({ country: value });
  },
}));
