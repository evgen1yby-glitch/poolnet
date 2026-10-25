import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const KEY_SUB = 'poolnet.subscription';
const KEY_COUNTRY = 'poolnet.country';
const KEY_ONBOARDED = 'poolnet.onboarded';
const KEY_LANG = 'poolnet.language';

async function setItem(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function getItem(key: string): Promise<string | null> {
  if (Platform.OS === 'web') return localStorage.getItem(key);
  return SecureStore.getItemAsync(key);
}

async function removeItem(key: string): Promise<void> {
  if (Platform.OS === 'web') {
    localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export type StoredLanguage = 'ru' | 'en';
export type StoredSubscription = { token: string; url: string; expiresAt: string };
export type StoredCountry = { cc: string; name: string; nodes: number };

export const storage = {
  getSubscription: async (): Promise<StoredSubscription | null> => {
    const raw = await getItem(KEY_SUB);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as StoredSubscription;
      if (!parsed.token || !parsed.url || !parsed.expiresAt) return null;
      return parsed;
    } catch {
      return null;
    }
  },
  setSubscription: (value: StoredSubscription) => setItem(KEY_SUB, JSON.stringify(value)),
  clearSubscription: () => removeItem(KEY_SUB),
  getCountry: async (): Promise<StoredCountry | null> => {
    const raw = await getItem(KEY_COUNTRY);
    if (!raw) return null;
    try { return JSON.parse(raw) as StoredCountry; } catch { return null; }
  },
  setCountry: (value: StoredCountry) => setItem(KEY_COUNTRY, JSON.stringify(value)),
  clearCountry: () => removeItem(KEY_COUNTRY),
  getLanguage: async (): Promise<StoredLanguage | null> => {
    const value = await getItem(KEY_LANG);
    return value === 'ru' || value === 'en' ? value : null;
  },
  setLanguage: (value: StoredLanguage) => setItem(KEY_LANG, value),
  getOnboarded: async () => (await getItem(KEY_ONBOARDED)) === '1',
  setOnboarded: () => setItem(KEY_ONBOARDED, '1'),
};
