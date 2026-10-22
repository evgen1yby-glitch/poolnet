/**
 * The benchmark layer: instead of publishing raw volume, this measures what
 * each public list is actually worth. Every number here is produced by this
 * pipeline's own checks — never by the source's claims.
 */
export interface SourceMetric {
  id: string;
  /** entries this pipeline actually checked for the source this cycle */
  candidates: number;
  /** of those, how many answered a full request right now */
  alive: number;
  /** alive / candidates, 0..1 */
  liveRate: number;
  /** entries the source published in total this cycle; null when unknown */
  published: number | null;
  medianLatency: number | null;
  /** share of alive entries graded elite, 0..1; null when nothing alive */
  eliteRate: number | null;
  /** days since the source file last changed, null when unknown */
  staleDays: number | null;
}

export interface Benchmark {
  generatedAt: number;
  cycle: {
    parsed: number;
    unique: number;
    sampled: number;
    alive: number;
  };
  /** sorted by live rate, descending */
  sources: SourceMetric[];
  /** 1-based position in that order */
  ranks: Record<string, number>;
}

export interface HistoryPoint {
  ts: number;
  /** id -> rank (1-based) at that cycle */
  ranks: Record<string, number>;
  /** id -> live rate in percent at that cycle */
  live: Record<string, number>;
}

export interface CycleStats {
  ts: number;
  total: number;
  http: number;
  socks4: number;
  socks5: number;
  medianLatency: number | null;
  /** share of elite in the published pool, 0..1 */
  eliteRate: number | null;
  mitm: number;
  /** how many distinct countries the pool covered this cycle */
  countries: number;
  /** top countries as [iso, count] pairs */
  countriesTop: Array<[string, number]>;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2;
}

export interface RawSourceInput {
  id: string;
  /** how many of this source's entries were actually checked this cycle */
  candidates: number;
  /** how many entries the source published in total this cycle, if known */
  published?: number | null;
  staleDays: number | null;
  /** canonical keys this source published this cycle, for per-source credit */
  keys?: string[];
}

export interface RawAliveInput {
  /** canonical key of the alive proxy */
  key: string;
  latency: number | null;
  grade: string | null;
}

/**
 * Joins what sources published with what their entries actually did.
 * A source whose entries appear in several lists gets credit once per list,
 * so the live rate stays per-source rather than per-proxy.
 */
export function buildBenchmark(
  generatedAt: number,
  cycle: Benchmark['cycle'],
  raw: RawSourceInput[],
  aliveRows: RawAliveInput[],
): Benchmark {
  // A source's live rate is the share of the entries IT published that
  // answered. Counting a proxy for every list that also carried it would
  // inflate small sources past 100%. The rate is measured over the keys the
  // fetch job actually sampled for this source — the published count stays
  // in `published` for context and is never the denominator.
  const sources: SourceMetric[] = raw.map((r) => {
    const own = r.keys;
    const aliveRowsForSource = own ? aliveRows.filter((row) => own.includes(row.key ?? '')) : [];
    return {
      id: r.id,
      candidates: r.candidates,
      alive: aliveRowsForSource.length,
      liveRate: r.candidates > 0 ? aliveRowsForSource.length / r.candidates : 0,
      published: r.published ?? null,
      medianLatency: aliveRowsForSource.length
        ? median(aliveRowsForSource.map((x) => x.latency).filter((v): v is number => v !== null))
        : null,
      eliteRate: aliveRowsForSource.length
        ? aliveRowsForSource.filter((x) => x.grade === 'elite').length / aliveRowsForSource.length
        : null,
      staleDays: r.staleDays,
    };
  });

  sources.sort((a, b) => b.liveRate - a.liveRate || b.alive - a.alive || a.id.localeCompare(b.id));
  const ranks: Record<string, number> = {};
  sources.forEach((s, i) => {
    ranks[s.id] = i + 1;
  });

  return { generatedAt, cycle, sources, ranks };
}

/** Appends one cycle to the rank history, capped at `keep` points. */
export function appendHistory(previous: HistoryPoint[], bench: Benchmark, keep = 96): HistoryPoint[] {
  const live: Record<string, number> = {};
  for (const s of bench.sources) live[s.id] = Math.round(s.liveRate * 1000) / 10;
  const point: HistoryPoint = { ts: bench.generatedAt, ranks: bench.ranks, live };
  const next = [...previous, point];
  return next.length > keep ? next.slice(next.length - keep) : next;
}

/** Rank movement for a source between the two most recent cycles. */
export function rankDelta(history: HistoryPoint[], id: string): number | null {
  if (history.length < 2) return null;
  const [prev, cur] = [history[history.length - 2]!, history[history.length - 1]!];
  const a = prev.ranks[id];
  const b = cur.ranks[id];
  if (a === undefined || b === undefined) return null;
  return a - b; // positive = moved up
}
