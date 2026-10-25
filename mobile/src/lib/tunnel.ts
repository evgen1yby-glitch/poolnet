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

export async function tunnelStatus(): Promise<{ running: boolean; error: string | null }> {
  if (!nativeTunnel) return { running: false, error: null };
  return nativeTunnel.status();
}
