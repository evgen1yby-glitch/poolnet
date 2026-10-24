import path from 'node:path';
import { config, ensureDir } from '../config.js';
import { log } from '../log.js';
import { createStore } from '../store/index.js';
import { subnetOfHost } from '../store/types.js';
import { renderAll } from '../publish/render.js';
import { atomicWriteJson } from '../io/jsonl.js';

/** Command: re-render data/ from the stored pool without new checks. */
export async function cmdPublish(): Promise<number> {
  const cfg = config();
  ensureDir(cfg.dataDir);
  const store = createStore();
  try {
    const pool = await store.loadPool();
    const now = Date.now();
    const poolNow = [...pool.values()].filter((r) => (r.lastOk ?? 0) > now - cfg.publishFreshMs);
    const perSubnet = new Map<string, number>();
    const capped = poolNow.filter((r) => {
      const s = subnetOfHost(r.host);
      const n = (perSubnet.get(s) ?? 0) + 1;
      if (n > cfg.maxPerSubnet) return false;
      perSubnet.set(s, n);
      return true;
    });
    const report = renderAll(capped, {
      dataDir: cfg.dataDir,
      topN: cfg.topN,
      generatedAt: now,
      publishHistory: cfg.publishHistory,
      serverIp: process.env.OPP_SERVER_IP,
    });
    atomicWriteJson(path.join(cfg.dataDir, 'meta.json'), {
      generatedAt: now,
      generatedIso: new Date(now).toISOString(),
      runId: cfg.runId,
      pipeline: 'publish-only',
      counts: {
        poolSize: pool.size,
        freshPool: poolNow.length,
        afterSubnetCap: capped.length,
        published: report.total,
      },
      byProtocol: report.byProtocol,
    });
    log.info(`publish: ${report.total} proxies from pool of ${pool.size}`);
    return report.total;
  } finally {
    await store.close();
  }
}
