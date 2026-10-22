import http from 'node:http';
import { log } from '../log.js';
import { readCandidates } from './fetch.js';
import { Coordinator } from '../distributed/index.js';
import type { NodeReport } from '../distributed/index.js';

/**
 * Command: `opp serve` — the coordinator half of distributed verification.
 *
 * A volunteer node (`opp node`) has work handed to it over HTTP and posts
 * its results back. The coordinator decides what is handed out and only
 * accepts results for work it actually issued, so a lying node can neither
 * invent proxies nor claim credit it did not earn.
 */
export interface ServeOptions {
  port?: number;
  /** when set, /jobs and /results require `Authorization: Bearer <token>` */
  token?: string;
  once?: boolean;
}

const MAX_BODY_BYTES = 8 * 1024 * 1024;

const json = (res: http.ServerResponse, status: number, data: unknown) => {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
    'access-control-allow-headers': 'authorization,content-type',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
};

const readBody = (req: http.IncomingMessage): Promise<string> =>
  new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error('body too large'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });

export async function cmdServe(opts: ServeOptions = {}): Promise<http.Server> {
  const port = opts.port ?? Number(process.env.OPP_SERVE_PORT || 8787);
  const token = opts.token ?? process.env.OPP_SERVE_TOKEN ?? '';

  const coordinator = new Coordinator();
  const candidates = readCandidates();
  // credentials ride along: a node that cannot authenticate is a false negative
  const queued = coordinator.enqueue(
    candidates.map((c) => ({
      protocol: c.protocol,
      host: c.host,
      port: c.port,
      ...(c.user ? { user: c.user } : {}),
      ...(c.pass ? { pass: c.pass } : {}),
    })),
  );
  log.info(`serve: coordinator on :${port}, ${queued} candidates queued${token ? ', token auth on' : ''}`);

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'GET,POST,OPTIONS',
        'access-control-allow-headers': 'authorization,content-type',
        'access-control-max-age': '86400',
      });
      res.end();
      return;
    }
    const authorized = () => {
      if (!token) return true;
      const h = req.headers.authorization ?? '';
      return h === `Bearer ${token}`;
    };

    if (url.pathname === '/healthz') {
      json(res, 200, { ok: true, ...coordinator.stats() });
      return;
    }
    if (req.method === 'GET' && url.pathname === '/jobs') {
      if (!authorized()) return json(res, 401, { error: 'unauthorized' });
      const size = Math.max(1, Math.min(500, Number(url.searchParams.get('size') ?? 100) || 100));
      const job = coordinator.nextJob(size);
      if (!job) {
        res.writeHead(204);
        res.end();
        return;
      }
      json(res, 200, job);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/results') {
      if (!authorized()) return json(res, 401, { error: 'unauthorized' });
      try {
        const report = JSON.parse(await readBody(req)) as NodeReport;
        if (!report || typeof report.jobId !== 'string' || !Array.isArray(report.results)) {
          return json(res, 400, { error: 'malformed report' });
        }
        const accepted = coordinator.accept(report);
        json(res, 200, { accepted, ...coordinator.stats() });
      } catch (e) {
        json(res, 400, { error: (e as Error).message });
      }
      return;
    }
    json(res, 404, { error: 'not found', routes: ['GET /jobs', 'POST /results', 'GET /healthz'] });
  });

  await new Promise<void>((resolve) => server.listen(port, resolve));
  if (!opts.once) {
    for (const sig of ['SIGINT', 'SIGTERM'] as const) {
      process.on(sig, () => {
        log.info(`serve: ${sig}, ${coordinator.drain().length} results collected`);
        server.close(() => process.exit(0));
      });
    }
  }
  return server;
}
