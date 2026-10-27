import { NativeModules, Platform } from 'react-native';

type TunnelModule = {
  prepare: () => Promise<boolean>;
  start: (config: string) => Promise<boolean>;
  stop: () => Promise<boolean>;
  status: () => Promise<{ running: boolean; error: string | null }>;
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

async function probeOnce(timeoutMs: number): Promise<void> {
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
    if (!results.some((result) => result.status === 'fulfilled')) {
      throw new Error('tunnel probe failed');
    }
  } finally {
    clearTimeout(timer);
  }
}

export async function verifyTunnel(timeoutMs = 6000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = new Error('tunnel probe failed');
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    try {
      await probeOnce(Math.min(2500, remaining));
      return;
    } catch (error) {
      lastError = error;
      if (deadline - Date.now() > 1200) {
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
  }
  throw lastError;
}

export async function tunnelStatus(): Promise<{ running: boolean; error: string | null }> {
  if (!nativeTunnel) return { running: false, error: null };
  return nativeTunnel.status();
}
