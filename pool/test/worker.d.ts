// Type seam for the Cloudflare Worker (plain JS, deployed with wrangler).
declare module '*/workers/api/check.js' {
  export function checkProxyOnDemand(opts: {
    proxy: { protocol: 'http' | 'socks4' | 'socks5'; host: string; port: number };
    connect: (opts: { hostname: string; port: number }) => {
      writable: WritableStream<Uint8Array>;
      readable: ReadableStream<Uint8Array>;
      close(): Promise<void>;
    };
    targetUrl?: string;
    timeoutMs?: number;
  }): Promise<{ alive: boolean; remoteIp: string | null; latencyMs: number | null; error: string | null }>;
}

declare module '*/workers/api/index.js' {
  const worker: {
    fetch(request: Request, env: Partial<{ ORIGIN: string }>): Promise<Response>;
  };
  export default worker;
}
