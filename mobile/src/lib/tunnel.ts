import { NativeModules, Platform } from 'react-native';

type TunnelStatus = {
  running: boolean;
  error: string | null;
  startedAt: number;
  rxBytes: number;
  txBytes: number;
};

type TunnelModule = {
  prepare: () => Promise<boolean>;
  start: (config: string) => Promise<boolean>;
  stop: () => Promise<boolean>;
  status: () => Promise<Partial<TunnelStatus> & { running: boolean; error: string | null }>;
};

const nativeTunnel = NativeModules.XrayTunnel as TunnelModule | undefined;

export const tunnelSupported = Platform.OS === 'android' && Boolean(nativeTunnel);

export async function prepareTunnel(): Promise<boolean> {
  if (!nativeTunnel) throw new Error('VPN доступен только в Android-сборке');
  return nativeTunnel.prepare();
}

export async function startTunnel(config: string): Promise<void> {
  if (!nativeTunnel) throw new Error('VPN доступен только в Android-сборке');
  await nativeTunnel.start(config);
}

export async function stopTunnel(): Promise<void> {
  if (!nativeTunnel) return;
  await nativeTunnel.stop();
}

async function probeOnce(timeoutMs: number): Promise<string> {
  const endpoints = ['https://api.ipify.org', 'https://icanhazip.com'];
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const results = await Promise.allSettled(
      endpoints.map(async (endpoint) => {
        const response = await fetch(endpoint, {
          signal: controller.signal,
          cache: 'no-store',
          headers: { Accept: 'text/plain' },
        });
        const body = (await response.text()).trim();
        if (!response.ok || !/^\d{1,3}(\.\d{1,3}){3}$/.test(body)) {
          throw new Error('tunnel probe failed');
        }
        return body;
      }),
    );
    const ip = results.find(
      (result): result is PromiseFulfilledResult<string> => result.status === 'fulfilled',
    )?.value;
    if (!ip) throw new Error('tunnel probe failed');
    return ip;
  } finally {
    clearTimeout(timer);
  }
}

export async function verifyTunnel(timeoutMs = 6000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = new Error('tunnel probe failed');
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    try {
      return await probeOnce(Math.min(2500, remaining));
    } catch (error) {
      lastError = error;
      if (deadline - Date.now() > 1200) {
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
  }
  throw lastError;
}

export async function fetchExitIp(timeoutMs = 5000): Promise<string> {
  return probeOnce(timeoutMs);
}

export async function tunnelStatus(): Promise<TunnelStatus> {
  if (!nativeTunnel) {
    return { running: false, error: null, startedAt: 0, rxBytes: 0, txBytes: 0 };
  }
  const status = await nativeTunnel.status();
  return {
    running: Boolean(status.running),
    error: status.error ?? null,
    startedAt: Number(status.startedAt) || 0,
    rxBytes: Math.max(0, Number(status.rxBytes) || 0),
    txBytes: Math.max(0, Number(status.txBytes) || 0),
  };
}
