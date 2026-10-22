import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import zlib from 'node:zlib';
import { cmdServe } from '../src/cli/serve.js';
import { resetConfig } from '../src/config.js';

function writeCandidates(entries: Array<Record<string, unknown>>): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'opp-serve-'));
  process.env.OPP_WORK_DIR = dir;
  resetConfig(); // config() memoizes, the new work dir must be visible now
  fs.writeFileSync(
    path.join(dir, 'candidates.jsonl.gz'),
    zlib.gzipSync(entries.map((e) => JSON.stringify(e)).join('\n')),
  );
  return dir;
}

test('coordinator: hands out work and drops results it never assigned', async () => {
  const dir = writeCandidates(
    Array.from({ length: 4 }, (_, i) => ({
      protocol: 'socks5',
      host: `45.10.${i}.1`,
      port: 1080,
      seenBy: ['test-source'],
    })),
  );
  const server = await cmdServe({ port: 0, once: true });
  const port = (server.address() as { port: number }).port;

  const jobs = await fetch(`http://127.0.0.1:${port}/jobs?size=3`);
  assert.equal(jobs.status, 200);
  const job = (await jobs.json()) as { jobId: string; batch: Array<{ protocol: string; host: string; port: number }> };
  assert.equal(job.batch.length, 3);

  const report = {
    jobId: job.jobId,
    nodeId: 'test-node',
    results: [
      ...job.batch.map((b: { protocol: string; host: string; port: number }) => ({
        ...b,
        alive: true,
        latencyMs: 10,
        anonymity: 'elite',
        remoteIp: b.host,
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
  };
  const okRes = await fetch(`http://127.0.0.1:${port}/results`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(report),
  });
  assert.equal(okRes.status, 200);
  assert.equal(((await okRes.json()) as { accepted: number }).accepted, 3, 'the forged 4th result is dropped');

  const next = await fetch(`http://127.0.0.1:${port}/jobs?size=10`);
  assert.equal(next.status, 200, 'the remaining candidate is still queued');
  assert.equal(((await next.json()) as { batch: unknown[] }).batch.length, 1);

  assert.equal((await fetch(`http://127.0.0.1:${port}/healthz`)).status, 200);
  assert.equal((await fetch(`http://127.0.0.1:${port}/nope`)).status, 404);

  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.OPP_WORK_DIR;
});

test('coordinator: a token is required when one is configured', async () => {
  const dir = writeCandidates([]);
  const server = await cmdServe({ port: 0, once: true, token: 'secret-token' });
  const port = (server.address() as { port: number }).port;
  const noAuth = await fetch(`http://127.0.0.1:${port}/jobs`);
  assert.equal(noAuth.status, 401);
  const withAuth = await fetch(`http://127.0.0.1:${port}/jobs`, { headers: { authorization: 'Bearer secret-token' } });
  assert.equal(withAuth.status, 204, 'an empty queue answers 204');
  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.OPP_WORK_DIR;
});

test('coordinator: a malformed report is a 400, not a crash', async () => {
  const dir = writeCandidates([{ protocol: 'http', host: '45.10.0.1', port: 80, seenBy: ['test-source'] }]);
  const server = await cmdServe({ port: 0, once: true });
  const port = (server.address() as { port: number }).port;
  const bad = await fetch(`http://127.0.0.1:${port}/results`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: 'not json at all',
  });
  assert.equal(bad.status, 400);
  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.OPP_WORK_DIR;
});

test('end to end: a volunteer node completes a job against the real coordinator', async () => {
  const { startSocks5Server, startEchoServer } = await import('./helpers/mocks.js');
  const echo = await startEchoServer(0);
  const socks = await startSocks5Server({});
  const dir = writeCandidates([
    { protocol: 'socks5', host: '127.0.0.1', port: socks.port, seenBy: ['test-source'] },
    { protocol: 'socks5', host: '127.0.0.2', port: socks.port, seenBy: ['test-source'] },
  ]);
  const server = await cmdServe({ port: 0, once: true });
  const port = (server.address() as { port: number }).port;

  const { runNode } = await import('../src/distributed/index.js');
  const done = await runNode({
    coordinatorUrl: `http://127.0.0.1:${port}`,
    nodeId: 'volunteer',
    once: true,
    targets: [{ url: `http://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' }],
  });
  assert.equal(done, 2, 'both candidates were checked and reported');
  const health = (await (await fetch(`http://127.0.0.1:${port}/healthz`)).json()) as {
    results: number;
    queued: number;
  };
  assert.equal(health.results, 2, 'the coordinator accepted both reports');
  assert.equal(health.queued, 0);

  // a second poll finds nothing and the node exits cleanly on a 204
  const again = await runNode({
    coordinatorUrl: `http://127.0.0.1:${port}`,
    nodeId: 'volunteer',
    once: true,
    targets: [{ url: `http://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' }],
  });
  assert.equal(again, 0);

  server.close();
  await echo.close();
  await socks.close();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.OPP_WORK_DIR;
});

test('node: an unauthorized coordinator explains itself instead of crashing blind', async () => {
  const server = await cmdServe({ port: 0, once: true, token: 'secret-token' });
  const port = (server.address() as { port: number }).port;
  const { runNode } = await import('../src/distributed/index.js');
  await assert.rejects(
    () =>
      runNode({
        coordinatorUrl: `http://127.0.0.1:${port}`,
        nodeId: 'volunteer',
        once: true,
        targets: [{ url: 'http://127.0.0.1:1/get', parser: 'none', label: 'unused' }],
      }),
    /401/,
    'the auth failure must be visible, not a downstream TypeError',
  );
  server.close();
});

test('coordinator: credentials travel with the candidate', async () => {
  const dir = writeCandidates([
    { protocol: 'socks5', host: '45.10.0.1', port: 1080, user: 'u1', pass: 'p1', seenBy: ['test-source'] },
  ]);
  const server = await cmdServe({ port: 0, once: true });
  const port = (server.address() as { port: number }).port;
  const job = (await (await fetch(`http://127.0.0.1:${port}/jobs?size=5`)).json()) as {
    batch: Array<{ host: string; user?: string; pass?: string }>;
  };
  assert.equal(job.batch[0]!.host, '45.10.0.1');
  assert.equal(job.batch[0]!.user, 'u1', 'the node must be able to authenticate');
  assert.equal(job.batch[0]!.pass, 'p1');
  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.OPP_WORK_DIR;
});
