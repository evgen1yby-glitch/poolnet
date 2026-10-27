import { useEffect } from 'react';
import { AppState } from 'react-native';

import { pingPresence } from '@/lib/presence';
import { useAppStore } from '@/store/app';

export function AppPresence() {
  const hydrated = useAppStore((state) => state.hydrated);
  const connection = useAppStore((state) => state.connection);

  useEffect(() => {
    if (!hydrated) return;
    const connected = connection === 'connected';
    void pingPresence(connected, true);

    const timer = setInterval(() => {
      if (AppState.currentState === 'active') void pingPresence(connected);
    }, 5 * 60 * 1000);
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void pingPresence(connected, true);
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [connection, hydrated]);

  return null;
}
