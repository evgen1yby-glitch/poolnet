import fs from 'node:fs';
import YAML from 'yaml';
import { log } from '../log.js';
import { SUPPORTED_PROTOCOLS, type SourceSpec } from './types.js';

/**
 * Expands ${VAR} from the environment. Returns null when the variable is
 * missing, which the caller treats as "skip this source quietly".
 */
function expandEnv(value: string): string | null {
  return value.replace(/\$\{(\w+)\}/g, (m, name) => {
    const v = process.env[name];
    if (v === undefined || v === '') return m; // keep marker; caller detects it
    return v;
  });
}

const hasUnexpanded = (value: string) => /\$\{\w+\}/.test(value);

export function loadSources(file: string): { sources: SourceSpec[]; skipped: string[] } {
  const { sources, skipped } = parseSources(file);
  return { sources, skipped };
}

function parseSources(file: string): { sources: SourceSpec[]; skipped: string[] } {
  const raw = fs.readFileSync(file, 'utf8');
  const parsed = YAML.parse(raw) as { sources?: unknown };
  if (!parsed || !Array.isArray(parsed.sources)) {
    throw new Error(`${file}: expected top-level "sources" array`);
  }
  const out: SourceSpec[] = [];
  const seen = new Set<string>();
  const skipped: string[] = [];
  for (const item of parsed.sources) {
    const s = item as Partial<SourceSpec>;
    if (!s || typeof s.id !== 'string' || typeof s.url !== 'string') {
      log.warn(`sources: skipping malformed entry: ${JSON.stringify(item)}`);
      skipped.push('malformed');
      continue;
    }
    if (seen.has(s.id)) {
      log.warn(`sources: duplicate id ${s.id} skipped`);
      continue;
    }
    seen.add(s.id);
    if (
      s.format !== 'plain' &&
      s.format !== 'json' &&
      s.format !== 'html' &&
      s.format !== 'gfp' &&
      s.format !== 'spys' &&
      s.format !== 'advname' &&
      s.format !== 'roundproxies'
    ) {
      log.warn(`sources: ${s.id}: unknown format ${String(s.format)}, skipped`);
      skipped.push(s.id);
      continue;
    }
    if (s.protocol && !SUPPORTED_PROTOCOLS.includes(s.protocol)) {
      log.warn(`sources: ${s.id}: unsupported protocol ${s.protocol}, skipped`);
      skipped.push(s.id);
      continue;
    }
    const url = expandEnv(s.url);
    if (url === null || hasUnexpanded(url)) {
      log.info(
        `sources: ${s.id}: skipped — ${url === null ? 'url' : 'env'} placeholder unset (set the API key to enable)`,
      );
      skipped.push(s.id);
      continue;
    }
    if (s.method && s.method !== 'get' && s.method !== 'post') {
      log.warn(`sources: ${s.id}: unknown method ${String(s.method)}, skipped`);
      skipped.push(s.id);
      continue;
    }
    const auth = s.auth ? expandEnv(s.auth) : null;
    if (s.auth && (auth === null || hasUnexpanded(auth))) {
      log.info(`sources: ${s.id}: skipped — auth env unset (set the API key to enable)`);
      skipped.push(s.id);
      continue;
    }
    out.push({
      id: s.id,
      url,
      format: s.format,
      protocol: s.protocol,
      enabled: s.enabled !== false,
      auth: auth ?? undefined,
      method: s.method,
      body: s.body,
    });
  }
  return { sources: out, skipped };
}
