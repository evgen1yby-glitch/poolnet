import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import zlib from 'node:zlib';

async function storeIn(dir: string) {
  process.env.OPP_STATE_DIR = dir;
  const { createStore } = await import('../src/store/index.js');
  return createStore();
}

test('store: a corrupt snapshot fails loudly instead of resetting history', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-'));
  const file = path.join(dir, 'pool.json.gz');
  // a truncated gzip: what a killed cycle or a partial cache restore leaves
  const good = zlib.gzipSync(JSON.stringify({ version: 1, savedAt: Date.now(), proxies: [] }));
  fs.writeFileSync(file, good.subarray(0, Math.floor(good.length / 3)));
  const store = await storeIn(dir);
  await assert.rejects(() => store.loadPool(), /unreadable/, 'the run must not continue on a broken snapshot');
  delete process.env.OPP_STATE_DIR;
  fs.rmSync(dir, { recursive: true, force: true });
});

test('store: a missing snapshot is a normal first run', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'opp-store-'));
  const store = await storeIn(dir);
  assert.equal((await store.loadPool()).size, 0);
  delete process.env.OPP_STATE_DIR;
  fs.rmSync(dir, { recursive: true, force: true });
});
