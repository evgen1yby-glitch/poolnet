import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir } from '../config.js';
import { log } from '../log.js';
import { fetchSource } from '../sources/fetcher.js';
import { parseSource } from '../parse/index.js';
import { atomicWriteJson } from '../io/jsonl.js';
import YAML from 'yaml';

/**
 * Command: discover candidate sources via the GitHub API.
 *
 * We look at repos through two lenses: the `proxy-list` topic, and code hits
 * for well-known list file names. Every candidate URL is then probed for
 * real yield - a 200 response that parses zero proxies is not a source.
 *
 * Output: data/discover-report.md + data/discover-report.json (used by the
 * discover workflow to file an issue for human review).
 */

const TOPIC = 'proxy-list';

const PATH_CANDIDATES = [
  'proxies/socks5.txt',
  'proxies/http.txt',
  'proxies/https.txt',
  'proxies/socks4.txt',
  'proxies/all.txt',
  'socks5.txt',
  'http.txt',
  'https.txt',
  'socks4.txt',
  'proxy.txt',
  'all.txt',
  'working_proxies.txt',
  'proxylist.txt',
  'data.txt',
];

interface Repo {
  full_name: string;
  description?: string;
  stargazers_count?: number;
  pushed_at?: string;
}

interface CodeItem {
  repository: { full_name: string };
  path: string;
  html_url: string;
}

export interface Candidate {
  repo: string;
  url: string;
  path: string;
  candidates: number;
  stars?: number;
  reason: string;
}

function ghHeaders(token: string | undefined): Record<string, string> {
  const h: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': config().fetchUserAgent,
    'X-GitHub-Api-Version': '2022-11-28',
  };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function ghSearch(url: string, token: string | undefined): Promise<unknown> {
  try {
    const res = await fetch(url, { headers: ghHeaders(token) });
    if (!res.ok) {
      log.warn(`discover: search failed ${res.status} for ${url}`);
      return null;
    }
    return (await res.json()) as unknown;
  } catch (e) {
    log.warn(`discover: ${(e as Error).message}`);
    return null;
  }
}

export async function cmdDiscover(): Promise<{
  reposScanned: number;
  proposed: Candidate[];
  reportPath: string | null;
}> {
  const cfg = config();
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;

  const known = new Set<string>();
  for (const s of YAML.parse(fs.readFileSync(cfg.sourcesFile, 'utf8')).sources as Array<{ url: string }>) {
    known.add(normalizeRepoFile(s.url));
  }

  const repos = new Map<string, Repo>();

  const topicJson = (await ghSearch(
    `https://api.github.com/search/repositories?q=topic:${TOPIC}&sort=updated&order=desc&per_page=100`,
    token,
  )) as { items?: Repo[] } | null;
  for (const r of topicJson?.items ?? []) repos.set(r.full_name, r);

  const codeJson = (await ghSearch(
    `https://api.github.com/search/code?q=filename:socks5.txt+in:file&per_page=100`,
    token,
  )) as { items?: CodeItem[] } | null;
  for (const it of codeJson?.items ?? []) {
    if (!repos.has(it.repository.full_name)) {
      repos.set(it.repository.full_name, { full_name: it.repository.full_name });
    }
  }

  const proposed: Candidate[] = [];
  let scanned = 0;

  for (const repo of repos.values()) {
    scanned++;
    if (scanned > 120) break;
    for (const p of PATH_CANDIDATES) {
      const url = `https://raw.githubusercontent.com/${repo.full_name}/HEAD/${p}`;
      if (known.has(`${repo.full_name}/${p}`)) continue;
      const res = await fetchSource({
        id: `${repo.full_name}/${p}`,
        url,
        format: 'plain',
        protocol: 'socks5',
      });
      if (!res.ok) continue;
      const parsed = parseSource(res).length;
      if (parsed >= 50) {
        proposed.push({
          repo: repo.full_name,
          url,
          path: p,
          candidates: parsed,
          stars: repo.stargazers_count,
          reason: `${parsed} entries`,
        });
      }
    }
  }

  proposed.sort((a, b) => b.candidates - a.candidates);
  ensureDir(cfg.dataDir);

  // an empty sweep must leave no report behind: the workflow files a review
  // issue for whatever report exists, and a stale one would re-open the issue
  const stale = [path.join(cfg.dataDir, 'discover-report.md'), path.join(cfg.dataDir, 'discover-report.json')];
  for (const f of stale) if (fs.existsSync(f)) fs.rmSync(f);
  if (proposed.length === 0) {
    log.info(`discover: no candidates with yield >= 50 in ${scanned} repositories`);
    return { reposScanned: scanned, proposed, reportPath: null };
  }

  const reportPath = path.join(cfg.dataDir, 'discover-report.md');
  const lines = [
    '# Source discovery report',
    '',
    `Scanned ${scanned} repositories at ${new Date().toISOString()}.`,
    `Found ${proposed.length} candidate sources with yield >= 50 entries.`,
    '',
    '| repo | path | candidates | stars |',
    '| --- | --- | ---: | ---: |',
    ...proposed.map((c) => `| ${c.repo} | ${c.path} | ${c.candidates} | ${c.stars ?? ''} |`),
    '',
  ];
  fs.writeFileSync(reportPath, lines.join('\n'));
  atomicWriteJson(path.join(cfg.dataDir, 'discover-report.json'), { scanned, proposed });

  log.info(`discover: scanned=${scanned} proposed=${proposed.length}`);
  return { reposScanned: scanned, proposed, reportPath };
}

/** Turn a raw URL into "<owner/repo>/<path>" when it points at GitHub raw. */
function normalizeRepoFile(url: string): string {
  const m = /raw\.githubusercontent\.com\/([^/]+\/[^/]+)\/(?:refs\/heads\/)?([^/]+)\/(.+)$/.exec(url);
  if (m) return `${m[1]}/${m[3]}`;
  return url;
}
