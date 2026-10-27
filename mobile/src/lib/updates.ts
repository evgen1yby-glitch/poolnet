import Constants from 'expo-constants';
import * as Application from 'expo-application';
import * as Device from 'expo-device';
import { File, Paths } from 'expo-file-system';
import * as IntentLauncher from 'expo-intent-launcher';
import { Platform } from 'react-native';

const MANIFEST_URL = 'https://poolnet.online/app/version.json';
const APK_HOST = 'poolnet.online';
const APK_PATH_PREFIX = '/app/';
const MAX_APK_BYTES = 300 * 1024 * 1024;

export type UpdateNotes = { ru: string; en: string };

export type UpdateManifest = {
  versionName: string;
  versionCode: number;
  apkUrl: string;
  sha256: string;
  size: number;
  publishedAt?: string;
  releaseNotes: UpdateNotes;
};

export type UpdateCheck = {
  installedVersion: string;
  installedCode: number;
  available: boolean;
  manifest: UpdateManifest;
};

export type InstallResult =
  | { status: 'installer' }
  | { status: 'permission' }
  | { status: 'downloaded'; file: File };

function installedCode(): number {
  const native = Number(Application.nativeBuildVersion || '');
  if (Number.isInteger(native) && native > 0) return native;
  const configured = Number(Constants.expoConfig?.android?.versionCode || '');
  return Number.isInteger(configured) && configured > 0 ? configured : 0;
}

export function currentVersion(): { name: string; code: number } {
  const name =
    Application.nativeApplicationVersion ||
    Constants.expoConfig?.version ||
    '0.0.0';
  return { name, code: installedCode() };
}

function validateManifest(value: unknown): UpdateManifest {
  if (!value || typeof value !== 'object') throw new Error('invalid manifest');
  const raw = value as Record<string, unknown>;
  const versionName = typeof raw.versionName === 'string' ? raw.versionName.trim() : '';
  const versionCode = Number(raw.versionCode);
  const apkUrl = typeof raw.apkUrl === 'string' ? raw.apkUrl.trim() : '';
  const sha256 = typeof raw.sha256 === 'string' ? raw.sha256.trim().toLowerCase() : '';
  const size = Number(raw.size);
  if (!/^\d+\.\d+\.\d+(?:[-+].*)?$/.test(versionName)) throw new Error('invalid version');
  if (!Number.isSafeInteger(versionCode) || versionCode <= 0) throw new Error('invalid version code');
  if (!Number.isSafeInteger(size) || size <= 0 || size > MAX_APK_BYTES) {
    throw new Error('invalid size');
  }
  if (!/^[a-f0-9]{64}$/.test(sha256)) throw new Error('invalid checksum');
  let url: URL;
  try {
    url = new URL(apkUrl);
  } catch {
    throw new Error('invalid apk url');
  }
  if (url.protocol !== 'https:' || url.hostname !== APK_HOST || !url.pathname.startsWith(APK_PATH_PREFIX)) {
    throw new Error('untrusted apk url');
  }
  if (!url.pathname.endsWith('.apk')) throw new Error('invalid apk url');
  const notes = raw.releaseNotes && typeof raw.releaseNotes === 'object'
    ? (raw.releaseNotes as Record<string, unknown>)
    : {};
  return {
    versionName,
    versionCode,
    apkUrl: url.toString(),
    sha256,
    size,
    publishedAt: typeof raw.publishedAt === 'string' ? raw.publishedAt : undefined,
    releaseNotes: {
      ru: typeof notes.ru === 'string' ? notes.ru.slice(0, 1200) : '',
      en: typeof notes.en === 'string' ? notes.en.slice(0, 1200) : '',
    },
  };
}

export async function checkForUpdates(): Promise<UpdateCheck> {
  if (Platform.OS !== 'android') throw new Error('android only');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  let response: Response;
  try {
    response = await fetch(`${MANIFEST_URL}?t=${Date.now()}`, {
      cache: 'no-store',
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) throw new Error(`manifest ${response.status}`);
  const manifest = validateManifest(await response.json());
  const installed = currentVersion();
  return {
    installedVersion: installed.name,
    installedCode: installed.code,
    available: manifest.versionCode > installed.code,
    manifest,
  };
}

export async function openInstallSettings(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await IntentLauncher.startActivityAsync(
    IntentLauncher.ActivityAction.MANAGE_UNKNOWN_APP_SOURCES,
    { data: `package:${Application.applicationId || 'online.poolnet.mobile'}` },
  );
}

export async function downloadAndInstall(
  manifest: UpdateManifest,
  onProgress: (percent: number) => void,
): Promise<InstallResult> {
  if (Platform.OS !== 'android') throw new Error('android only');
  const destination = new File(Paths.cache, `PoolNet-Mobile-${manifest.versionName}.apk`);
  if (destination.exists) destination.delete();
  let downloaded: File;
  try {
    downloaded = await File.downloadFileAsync(manifest.apkUrl, destination, {
      idempotent: true,
      onProgress: ({ bytesWritten, totalBytes }) => {
        const total = totalBytes > 0 ? totalBytes : manifest.size;
        if (total > 0) onProgress(Math.min(100, Math.round((bytesWritten / total) * 100)));
      },
    });
    if (downloaded.size !== manifest.size) throw new Error('size mismatch');
    const digest = (await downloaded.digest('SHA-256')).toLowerCase();
    if (digest !== manifest.sha256) throw new Error('checksum mismatch');
  } catch (error) {
    try {
      if (destination.exists) destination.delete();
    } catch {
      // Best effort cleanup; the system can clear the cache later.
    }
    throw error;
  }

  let allowed = false;
  try {
    allowed = await Device.isSideLoadingEnabledAsync();
  } catch {
    allowed = false;
  }
  if (!allowed) {
    await openInstallSettings();
    return { status: 'permission' };
  }

  onProgress(100);
  await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
    data: downloaded.contentUri,
    type: 'application/vnd.android.package-archive',
    flags: 1,
  });
  return { status: 'installer' };
}
