import { log } from '../log.js';
import { checkProxy, type CheckOutcome } from './stage.js';
import type { ProxyTarget } from './proxy-client.js';
import { defaultTargets } from './targets.js';
import type { CheckResultRecord } from '../store/types.js';

export interface RunnerOptions {
  concurrency: number;
  timeoutMs: number;
  stage1TimeoutMs: number;
  targets: ReturnType<typeof defaultTargets>;
}

export interface RunStats {
  checked: number;
  alive: number;
  elapsedMs: number;
}

export async function checkAll(
  targets: ProxyTarget[],
  opts: RunnerOptions,
  onResult?: (r: CheckResultRecord) => void,
): Promise<{ results: CheckResultRecord[]; stats: RunStats }> {
  const started = Date.now();
  const results: CheckResultRecord[] = [];
  const inFlight = new Map<number, { p: ProxyTarget; t0: number }>();
  let i = 0;
  let alive = 0;

  // Watchdog: a check far beyond its budget is a hang, not slowness - a
  // stuck handshake on one proxy must not stop the batch.
  const watchdog = setInterval(() => {
    const now = Date.now();
    for (const [j, { p, t0 }] of inFlight) {
      if (now - t0 > opts.timeoutMs * 2) {
        log.warn(`watchdog: check #${j} ${p.protocol}://${p.host}:${p.port} exceeded budget (${now - t0}ms)`);
      }
    }
  }, 5000);
  watchdog.unref();

  const worker = async () => {
    for (;;) {
      const j = i++;
      if (j >= targets.length) return;
      const p = targets[j]!;
      inFlight.set(j, { p, t0: Date.now() });
      const outcome = await checkProxy(p, {
        timeoutMs: opts.timeoutMs,
        stage1TimeoutMs: opts.stage1TimeoutMs,
        targets: opts.targets,
      }).finally(() => inFlight.delete(j));
      if (outcome.alive) alive++;
      const rec = toRecord(p, outcome);
      results.push(rec);
      onResult?.(rec);
      if (j % 200 === 0 && j > 0) {
        log.info(`check: ${j}/${targets.length} alive=${alive}`);
      }
    }
  };

  await Promise.all(Array.from({ length: Math.max(1, opts.concurrency) }, worker));
  clearInterval(watchdog);
  return { results, stats: { checked: targets.length, alive, elapsedMs: Date.now() - started } };
}

export function toRecord(p: ProxyTarget & { seenBy?: string[] }, o: CheckOutcome): CheckResultRecord {
  return {
    protocol: p.protocol,
    host: p.host,
    port: p.port,
    user: p.user,
    pass: p.pass,
    alive: o.alive,
    latencyMs: o.latencyMs,
    remoteIp: o.remoteIp,
    anonymity: o.anonymity,
    tlsIssuer: o.tlsIssuer,
    tlsMitm: o.tlsMitm,
    supportsTls: o.supportsTls,
    error: o.error,
    checkedAt: Date.now(),
    seenBy: p.seenBy ?? [],
  };
}
