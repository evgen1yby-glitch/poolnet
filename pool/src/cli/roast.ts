import fs from 'node:fs';
import path from 'node:path';
import { config } from '../config.js';
import { log } from '../log.js';
import { atomicWriteJson } from '../io/jsonl.js';
import type { Benchmark, HistoryPoint, SourceMetric } from '../benchmark/index.js';

/**
 * Command: `opp roast`.
 *
 * Turns one cycle of benchmark measurements into a publishable digest: the
 * lists with the biggest gap between what they publish and what actually
 * answers, the most honest ones, rank movement and staleness. The content
 * writes itself from data the pipeline already collects, which is the whole
 * point of the measurement layer.
 */
export interface Roast {
  generatedIso: string;
  cycle: Benchmark['cycle'];
  biggestFraud: SourceMetric | null;
  mostHonest: SourceMetric | null;
  leastAlive: SourceMetric | null;
  rising: Array<{ id: string; from: number; to: number }>;
  falling: Array<{ id: string; from: number; to: number }>;
  stalest: SourceMetric | null;
  freshest: SourceMetric | null;
  totalAliveBySource: number;
}

function pct(v: number): string {
  return `${(v * 100).toFixed(2)}%`;
}

export function buildRoast(bench: Benchmark, history: HistoryPoint[], generatedAt: number): Roast {
  // volume still decides impact: a tiny list saying "0%" proves nothing
  const volume = (s: SourceMetric) => s.published ?? s.candidates;
  const eligible = bench.sources.filter((s) => volume(s) >= 100);
  const biggestFraud = eligible.length ? eligible.reduce((a, b) => (a.liveRate <= b.liveRate ? a : b)) : null;
  const mostHonest = eligible.length ? eligible.reduce((a, b) => (a.liveRate >= b.liveRate ? a : b)) : null;
  const leastAlive = bench.sources.filter((s) => volume(s) >= 1000).sort((a, b) => a.liveRate - b.liveRate)[0] ?? null;
  const staleKnown = bench.sources.filter((s) => s.staleDays !== null);
  const stalest = staleKnown.length
    ? staleKnown.reduce((a, b) => ((a.staleDays ?? 0) >= (b.staleDays ?? 0) ? a : b))
    : null;
  const freshest = staleKnown.length
    ? staleKnown.reduce((a, b) => ((a.staleDays ?? 9999) <= (b.staleDays ?? 9999) ? a : b))
    : null;

  const [prev, cur] = [history[history.length - 2], history[history.length - 1]];
  const rising: Roast['rising'] = [];
  const falling: Roast['falling'] = [];
  if (prev && cur) {
    for (const [id, to] of Object.entries(cur.ranks)) {
      const from = prev.ranks[id];
      if (from === undefined || to === undefined) continue;
      if (from - to > 0) rising.push({ id, from, to });
      if (to - from > 0) falling.push({ id, from, to });
    }
    // sort by the size of the move, not by the raw ranks
    rising.sort((a, b) => b.from - b.to - (a.from - a.to));
    falling.sort((a, b) => b.to - b.from - (a.to - a.from));
  }

  return {
    generatedIso: new Date(generatedAt).toISOString(),
    cycle: bench.cycle,
    biggestFraud,
    mostHonest,
    leastAlive,
    rising: rising.slice(0, 5),
    falling: falling.slice(0, 5),
    stalest,
    freshest,
    totalAliveBySource: bench.sources.reduce((s, x) => s + x.alive, 0),
  };
}

export function renderRoast(roast: Roast): string {
  const L: string[] = [];
  L.push('# Weekly roast');
  L.push('');
  L.push(
    `Measured ${roast.generatedIso}. One cycle read ${roast.cycle.parsed.toLocaleString('en-US')} lines, ` +
      `deduplicated to ${(roast.cycle.unique / 1000).toFixed(0)}k candidates, sampled ${roast.cycle.sampled.toLocaleString('en-US')} ` +
      `— and ${roast.cycle.alive.toLocaleString('en-US')} answered a full request.`,
  );
  L.push('');

  if (roast.biggestFraud) {
    const f = roast.biggestFraud;
    L.push('## Biggest gap this week');
    L.push('');
    L.push(
      `**${f.id}** published ${(f.published ?? f.candidates).toLocaleString('en-US')} entries, ` +
        `${f.candidates.toLocaleString('en-US')} of which this pipeline checked — ` +
        `${f.alive.toLocaleString('en-US')} answered (${pct(f.liveRate)}).`,
    );
    L.push('');
    if (roast.leastAlive && roast.leastAlive.id !== f.id) {
      const l = roast.leastAlive;
      L.push(
        `**${l.id}** published ${(l.published ?? l.candidates).toLocaleString('en-US')} and answered ` +
          `${l.alive.toLocaleString('en-US')} of ${l.candidates.toLocaleString('en-US')} checked (${pct(l.liveRate)}).`,
      );
      L.push('');
    }
  }

  if (roast.mostHonest) {
    const h = roast.mostHonest;
    L.push('## Most honest source');
    L.push('');
    L.push(
      `**${h.id}** — ${pct(h.liveRate)} of published entries answered (${h.alive}/${h.candidates}), ` +
        `median latency ${h.medianLatency ?? '—'} ms.`,
    );
    L.push('');
  }

  if (roast.rising.length) {
    L.push('## Climbing');
    L.push('');
    for (const r of roast.rising) L.push(`- **${r.id}**: #${r.from} → #${r.to}`);
    L.push('');
  }
  if (roast.falling.length) {
    L.push('## Slipping');
    L.push('');
    for (const r of roast.falling) L.push(`- **${r.id}**: #${r.from} → #${r.to}`);
    L.push('');
  }

  L.push('## Freshness');
  L.push('');
  if (roast.stalest) {
    L.push(`- Stalest file: **${roast.stalest.id}** — untouched for ${roast.stalest.staleDays} days`);
  }
  if (roast.freshest) {
    L.push(`- Freshest file: **${roast.freshest.id}** — updated ${roast.freshest.staleDays} days ago`);
  }
  L.push('');
  L.push('---');
  L.push("*Every number on this page comes from this pipeline's own checks, not from any source's claims.*");
  return L.join('\n');
}

export async function cmdRoast(): Promise<{ roast: Roast; markdown: string; outPath: string }> {
  const cfg = config();
  const benchPath = path.join(cfg.dataDir, 'benchmark.json');
  const historyPath = path.join(cfg.dataDir, 'source-history.json');
  if (!fs.existsSync(benchPath)) {
    throw new Error(`${benchPath} not found — run the pipeline once first`);
  }
  const bench = JSON.parse(fs.readFileSync(benchPath, 'utf8')) as Benchmark;
  const history: HistoryPoint[] = fs.existsSync(historyPath)
    ? (JSON.parse(fs.readFileSync(historyPath, 'utf8')) as HistoryPoint[])
    : [];

  const roast = buildRoast(bench, history, Date.now());
  const markdown = renderRoast(roast);
  const outPath = path.join(cfg.dataDir, 'roast.md');
  fs.writeFileSync(outPath, markdown);
  atomicWriteJson(path.join(cfg.dataDir, 'roast.json'), roast);
  log.info(`roast: written to ${outPath}`);
  return { roast, markdown, outPath };
}
