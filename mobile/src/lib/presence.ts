import Constants from 'expo-constants';
import * as Application from 'expo-application';
import * as Device from 'expo-device';
import { Platform } from 'react-native';

import { api } from './api';
import { diagnosticLog, logEvent } from './diagnostics';
import { storage } from './storage';

let cachedId: string | null = null;
let lastPing = 0;

function randomId(): string {
  const bytes = new Uint8Array(24);
  const cryptoObject = globalThis.crypto;
  if (cryptoObject && typeof cryptoObject.getRandomValues === 'function') {
    cryptoObject.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
    bytes[0] ^= Date.now() & 0xff;
  }
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
}

export async function installId(): Promise<string> {
  if (cachedId) return cachedId;
  const stored = await storage.getInstallId();
  if (stored) {
    cachedId = stored;
    return stored;
  }
  const created = randomId();
  await storage.setInstallId(created);
  cachedId = created;
  return created;
}

export async function pingPresence(connected: boolean, force = false): Promise<void> {
  if (!force && Date.now() - lastPing < 30_000) return;
  lastPing = Date.now();
  try {
    await api.appPing({
      id: await installId(),
      version: Application.nativeApplicationVersion || Constants.expoConfig?.version || 'unknown',
      platform: Platform.OS,
      locale: Intl.DateTimeFormat().resolvedOptions().locale || 'ru',
      connected,
    });
  } catch {
    // Presence is best-effort and must never affect the VPN.
  }
}

export async function requestAppAccess(rotate = false) {
  return api.appAccess({
    id: await installId(),
    version: Application.nativeApplicationVersion || Constants.expoConfig?.version || 'unknown',
    platform: Platform.OS,
    locale: Intl.DateTimeFormat().resolvedOptions().locale || 'ru',
    rotate,
  });
}

export async function sendDiagnostics(meta: Record<string, unknown>): Promise<number> {
  const report = await api.appDiagnostics({
    id: await installId(),
    version: Application.nativeApplicationVersion || Constants.expoConfig?.version || 'unknown',
    platform: Platform.OS,
    locale: Intl.DateTimeFormat().resolvedOptions().locale || 'ru',
    logs: diagnosticLog(),
    meta: {
      ...meta,
      device: Device.modelName || Device.deviceName || 'unknown',
      os: `${Platform.OS} ${Platform.Version}`,
      build: Application.nativeBuildVersion || 'unknown',
    },
  });
  logEvent('info', 'diagnostics', 'sent', { report: report.report });
  return report.report;
}
