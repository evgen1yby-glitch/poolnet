import Constants from 'expo-constants';

const BASE =
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ||
  'https://poolnet.online';

export class ApiError extends Error {
  status: number;
  code?: string;
  retryAfter?: number;
  constructor(message: string, status: number, code?: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Accept: 'application/json', ...(init?.headers || {}) },
    });
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const retry = Number(response.headers.get('retry-after') || body.retry_after || 0);
      throw new ApiError(
        typeof body.error === 'string' ? body.error : 'Сервис недоступен',
        response.status,
        typeof body.code === 'string' ? body.code : undefined,
        retry || undefined,
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('Сервер не ответил вовремя', 0, 'timeout');
    }
    throw new ApiError('Нет соединения с сервером', 0, 'network');
  } finally {
    clearTimeout(timeout);
  }
}

export type StatusPayload = {
  vpn: {
    generation: string;
    verified: number;
    known: number;
    by_country: { name: string; n: number }[];
  };
  pool: {
    available: boolean;
    total: number;
    generated_iso: string;
    countries_count: number;
  };
};

export type ProxyRow = {
  rank: number;
  address: string;
  protocol: string;
  grade: string;
  latency_ms: number | null;
  uptime_7d: number | null;
  uptime_30d: number | null;
  country: string;
};

export type ProxiesPayload = {
  available: boolean;
  total: number;
  page: number;
  per: number;
  pages: number;
  generated_utc: string;
  rows: ProxyRow[];
  countries: { cc: string; n: number }[];
};

export type FreeStatus = {
  available: boolean;
  retry_after: number;
  claim_hours: number;
  wait_seconds: number;
};

export type FreeChallenge = { challenge: string; wait_seconds: number; claim_hours: number };
export type FreeKey = { token: string; expires_at: string | null; unlimited?: boolean; subscription: string };
export type AppPing = { id: string; version: string; platform: string; locale: string; connected: boolean };
export type AppAccessKey = { token: string; subscription: string; expires_at: string | null; unlimited?: boolean };
export type AppAccessPayload = Omit<AppPing, 'connected'> & { rotate?: boolean };
export type DiagnosticsPayload = { id: string; version: string; platform: string; locale: string; logs: string; meta: Record<string, unknown> };

export const api = {
  status: () => request<StatusPayload>('/api/status.json'),
  proxies: (params: { page?: number; per?: number; q?: string; proto?: string; country?: string }) => {
    const search = new URLSearchParams();
    search.set('page', String(params.page ?? 1));
    search.set('per', String(params.per ?? 50));
    if (params.q) search.set('q', params.q);
    if (params.proto) search.set('proto', params.proto);
    if (params.country) search.set('country', params.country);
    return request<ProxiesPayload>(`/api/proxies?${search.toString()}`);
  },
  freeStatus: () => request<FreeStatus>('/api/free-status'),
  freeChallenge: () => request<FreeChallenge>('/api/free-challenge'),
  appDiagnostics: (payload: DiagnosticsPayload) =>
    request<{ ok: boolean; report: number }>('/api/app/diagnostics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  appAccess: (payload: AppAccessPayload) =>
    request<AppAccessKey>('/api/app/access', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  appPing: (payload: AppPing) =>
    request<{ ok: boolean }>('/api/app/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  freeClaim: (challenge: string) =>
    request<FreeKey>('/api/free-subscription', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ challenge }),
    }),
};
