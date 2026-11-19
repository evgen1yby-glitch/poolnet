import { useEffect } from 'react';

import { verifyTunnel } from '@/lib/tunnel';
import { useAppStore } from '@/store/app';

const HEALTH_INTERVAL = 12_000;

export function TunnelSupervisor() {
  const connection = useAppStore((state) => state.connection);

  useEffect(() => {
    if (connection !== 'connected') return;
    let cancelled = false;
    let checking = false;
    let failures = 0;

    const check = async () => {
      if (cancelled || checking || useAppStore.getState().connection !== 'connected') return;
      checking = true;
      try {
        await verifyTunnel(4000);
        failures = 0;
      } catch {
        failures += 1;
        // A single slow probe is usually a transient packet loss. Reconnecting
        // after every one caused unnecessary tunnel churn; require two.
        if (!cancelled && failures >= 2) await useAppStore.getState().recover();
      } finally {
        checking = false;
      }
    };

    const timer = setInterval(() => void check(), HEALTH_INTERVAL);
    const kickoff = setTimeout(() => void check(), 5_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
      clearTimeout(kickoff);
    };
  }, [connection]);

  return null;
}
