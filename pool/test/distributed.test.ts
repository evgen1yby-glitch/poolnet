import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Coordinator, type NodeReport } from '../src/distributed/index.js';

const cand = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    protocol: 'socks5' as const,
    host: `10.${Math.floor(i / 256)}.${i % 256}.1`,
    port: 1080,
  }));

const report = (
  jobId: string,
  batch: Array<{ protocol: 'http' | 'socks4' | 'socks5'; host: string; port: number }>,
  over: Partial<NodeReport> = {},
): NodeReport => ({
  jobId,
  nodeId: 'test-node',
  results: batch.map((b) => ({
    protocol: b.protocol,
    host: b.host,
    port: b.port,
    alive: true,
    latencyMs: 100,
    anonymity: 'elite',
    remoteIp: b.host,
    tlsMitm: false,
    error: null,
  })),
  ...over,
});

test('coordinator: hands out batches and accepts reports', () => {
  const c = new Coordinator();
  assert.equal(c.enqueue(cand(600)), 600);
  const job = c.nextJob(500)!;
  assert.equal(job.batch.length, 500);
  assert.equal(c.accept(report(job.jobId, job.batch)), 500);
  const drained = c.drain();
  assert.equal(drained.length, 500);
  assert.equal(drained[0]!.anonymity, 'elite');
  assert.deepEqual(drained[0]!.seenBy, ['node:test-node']);
});

test('coordinator: rejects results for proxies that were not in the job', () => {
  const c = new Coordinator();
  c.enqueue(cand(10));
  const job = c.nextJob(5)!;
  const forged = report(job.jobId, job.batch, {
    results: [
      ...job.batch.map((b) => ({
        protocol: b.protocol,
        host: b.host,
        port: b.port,
        alive: true,
        latencyMs: 1,
        anonymity: 'elite',
        remoteIp: null,
        tlsMitm: false,
        error: null,
      })),
      {
        protocol: 'http',
        host: '9.9.9.9',
        port: 80,
        alive: true,
        latencyMs: 1,
        anonymity: 'elite',
        remoteIp: null,
        tlsMitm: false,
        error: null,
      },
    ],
  });
  assert.equal(c.accept(forged), 5, 'the forged entry is dropped');
});

test('coordinator: unknown job ids are ignored', () => {
  const c = new Coordinator();
  c.enqueue(cand(4));
  assert.equal(c.accept(report('job-does-not-exist', [])), 0);
});

test('coordinator: empty queue yields no job', () => {
  const c = new Coordinator();
  assert.equal(c.nextJob(), null);
});

test('coordinator: queue drains exactly once', () => {
  const c = new Coordinator();
  c.enqueue(cand(7));
  const first = c.nextJob(10)!;
  assert.equal(first.batch.length, 7);
  assert.equal(c.nextJob(), null);
});
