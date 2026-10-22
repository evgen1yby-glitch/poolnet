/**
 * Distributed verification: a volunteer node contributes check capacity and
 * receives work over plain HTTP.
 *
 * A node polls the coordinator for a batch of candidates, runs the same
 * checker the pipeline uses, and posts the results back. The coordinator
 * (Actions) merges node results with its own — nodes add capacity, they do
 * not replace the pipeline, and a malicious node can only lie about its own
 * results, which the cross-check by other nodes and by CI catches.
 *
 * Node side (run anywhere with outbound HTTPS):
 *   COORDINATOR_URL=https://… NODE_TOKEN=… npx tsx src/cli/node.ts
 *
 * Coordinator side: see `coordinator()` below — it is mounted by the
 * `opp serve` command when `OPP_NODE_MODE=1`.
 */
import { config } from '../config.js';
import { log } from '../log.js';
import { checkAll } from '../check/runner.js';
import { defaultTargets } from '../check/targets.js';
import type { CheckResultRecord } from '../store/types.js';

export type NodeCandidate = {
  protocol: 'http' | 'socks4' | 'socks5';
  host: string;
  port: number;
  /** present when the source published the proxy with credentials */
  user?: string;
  pass?: string;
};

export interface NodeJob {
  jobId: string;
  batch: NodeCandidate[];
  budgetMs: number;
}

export interface NodeReport {
  jobId: string;
  nodeId: string;
  results: Array<{
    protocol: string;
    host: string;
    port: number;
    alive: boolean;
    latencyMs: number | null;
    anonymity: string;
    remoteIp: string | null;
    tlsMitm: boolean;
    error: string | null;
  }>;
}

const MAX_BATCH = 500;

/** Coordinator: hand out work, accept results. */
export class Coordinator {
  private queue = new Map<string, NodeCandidate>();
  private jobs = new Map<
    string,
    { batch: Array<{ protocol: 'http' | 'socks4' | 'socks5'; host: string; port: number }>; issuedAt: number }
  >();
  private results: CheckResultRecord[] = [];
  private jobCounter = 0;

  enqueue(candidates: Array<{ protocol: string; host: string; port: number }>): number {
    for (const c of candidates) {
      this.queue.set(
        `${c.protocol}://${c.host}:${c.port}`,
        c as { protocol: 'http' | 'socks4' | 'socks5'; host: string; port: number },
      );
    }
    return this.queue.size;
  }

  /** Next batch for a node, or null when the queue is empty. */
  nextJob(size = MAX_BATCH): NodeJob | null {
    const batch: NodeCandidate[] = [];
    for (const [id, c] of this.queue) {
      batch.push(c);
      this.queue.delete(id);
      if (batch.length >= size) break;
    }
    if (!batch.length) return null;
    const jobId = `job-${++this.jobCounter}`;
    this.jobs.set(jobId, { batch, issuedAt: Date.now() });
    return { jobId, batch, budgetMs: config().checkTimeoutMs };
  }

  accept(report: NodeReport): number {
    const job = this.jobs.get(report.jobId);
    if (!job) return 0;
    this.jobs.delete(report.jobId);
    let accepted = 0;
    const valid = new Set(job.batch.map((b) => `${b.protocol}://${b.host}:${b.port}`));
    for (const r of report.results) {
      if (!valid.has(`${r.protocol}://${r.host}:${r.port}`)) continue; // not in this job
      this.results.push({
        protocol: r.protocol,
        host: r.host,
        port: r.port,
        alive: r.alive,
        latencyMs: r.latencyMs,
        remoteIp: r.remoteIp,
        anonymity: (r.anonymity || 'unknown') as CheckResultRecord['anonymity'],
        // a node report carries no TLS facts; claiming support would poison
        // every TLS-derived metric the pool publishes
        tlsIssuer: null,
        tlsMitm: r.tlsMitm,
        supportsTls: false,
        error: r.error,
        checkedAt: Date.now(),
        seenBy: [`node:${report.nodeId}`],
      });
      accepted++;
    }
    return accepted;
  }

  drain(): CheckResultRecord[] {
    const out = this.results;
    this.results = [];
    return out;
  }

  stats(): { queued: number; inFlight: number; results: number } {
    return { queued: this.queue.size, inFlight: this.jobs.size, results: this.results.length };
  }
}

const REQUEST_TIMEOUT_MS = 30_000;

/**
 * Node: poll the coordinator, check, report.
 *
 * A long-running poller must survive a coordinator hiccup: every request is
 * bounded, non-OK responses are explained, and backoff replaces dying.
 */
export async function runNode(opts: {
  coordinatorUrl: string;
  nodeId: string;
  token?: string;
  batchSize?: number;
  once?: boolean;
  /** stop after this many polls, for tests and one-shot runs */
  maxPolls?: number;
  /** echo targets; defaults to the production set (tests inject local ones) */
  targets?: import('../check/errors.js').EchoTarget[];
}): Promise<number> {
  const cfg = config();
  const batchSize = opts.batchSize ?? MAX_BATCH;
  const base = opts.coordinatorUrl.replace(/\/$/, '');
  let done = 0;
  let polls = 0;
  let backoffMs = 0;
  for (;;) {
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (opts.token) headers.authorization = `Bearer ${opts.token}`;
    try {
      const res = await fetch(`${base}/jobs?size=${batchSize}`, {
        headers,
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (res.status === 204) {
        if (opts.once || (opts.maxPolls !== undefined && ++polls >= opts.maxPolls)) break;
        await new Promise((r) => setTimeout(r, 5000));
        continue;
      }
      if (!res.ok) {
        // the coordinator explains itself; a node that ignores the reason is
        // impossible to debug from the outside
        const detail = await res.text().catch(() => '');
        throw new Error(`coordinator GET /jobs -> ${res.status} ${detail.slice(0, 200)}`);
      }
      const job = (await res.json()) as NodeJob;
      const { results } = await checkAll(job.batch, {
        concurrency: cfg.checkConcurrency,
        timeoutMs: job.budgetMs || cfg.checkTimeoutMs,
        stage1TimeoutMs: cfg.stage1TimeoutMs,
        targets: opts.targets ?? defaultTargets(),
      });
      const report: NodeReport = {
        jobId: job.jobId,
        nodeId: opts.nodeId,
        results: results.map((r) => ({
          protocol: r.protocol,
          host: r.host,
          port: r.port,
          alive: r.alive,
          latencyMs: r.latencyMs,
          anonymity: r.anonymity,
          remoteIp: r.remoteIp,
          tlsMitm: r.tlsMitm,
          error: r.error,
        })),
      };
      const post = await fetch(`${base}/results`, {
        method: 'POST',
        headers,
        body: JSON.stringify(report),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (!post.ok) {
        log.warn(`node: coordinator rejected report (${post.status}), will retry this job next poll`);
        continue;
      }
      done += results.length;
      backoffMs = 0;
      if (opts.once) break;
      if (opts.maxPolls !== undefined && ++polls >= opts.maxPolls) break;
    } catch (e) {
      if (opts.once) throw e;
      backoffMs = Math.min(60_000, backoffMs === 0 ? 1000 : backoffMs * 2);
      log.warn(`node: ${(e as Error).message}; retrying in ${backoffMs}ms`);
      await new Promise((r) => setTimeout(r, backoffMs));
    }
  }
  return done;
}
