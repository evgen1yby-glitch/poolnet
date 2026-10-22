import { config } from '../config.js';
import { log } from '../log.js';
import path from 'node:path';
import { FsStore } from './fs.js';
import { PostgresStore } from './postgres.js';
import type { Store } from './types.js';

export type { Store };

export function poolFile(): string {
  return process.env.OPP_POOL_FILE || path.join(config().stateDir, 'pool.json.gz');
}

export function createStore(): Store {
  const cfg = config();
  if (cfg.store === 'postgres') {
    if (!cfg.databaseUrl) throw new Error('STORE=postgres requires DATABASE_URL');
    const store = new PostgresStore(cfg.databaseUrl);
    void store.migrate();
    return store;
  }
  log.info(`store: fs snapshot at ${poolFile()}`);
  return new FsStore(poolFile());
}
