// Type seam for the dependency-free ESM bot, so tests typecheck without
// pulling the runtime file into the TS program.
declare module '*/bot/index.mjs' {
  export interface PoolEntry {
    id: string;
    protocol: string;
    host: string;
    port: number;
    grade: string;
    latency: number | null;
    country: string | null;
    city: string | null;
    uptime7d: number | null;
    mitm: boolean;
  }
  export interface ParsedCommand {
    name: string;
    protocol: string | null;
    country: string | null;
    size: number | null;
  }
  export function pickFrom(
    pool: PoolEntry[],
    filters: { protocol?: string | null; country?: string | null },
  ): PoolEntry | null;
  export function formatProxy(p: PoolEntry): string;
  export function formatStats(meta: {
    total: number;
    byProtocol: Record<string, number>;
    countries: Array<{ cc: string; n: number }>;
    medianLatencyMs: number | null;
    p95LatencyMs: number | null;
    sourcesOk: number;
    sourcesTotal: number;
    generatedIso: string;
  }): string;
  export function parseCommand(text: string): ParsedCommand;
  export function resolveFilters(
    parsed: ParsedCommand,
    knownCountries: string[],
  ): { protocol: string | null; country: string | null; typo: string | null };
}
