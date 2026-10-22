#!/usr/bin/env node
/**
 * Structural guard for the site. The site is a set of pages (index,
 * benchmark, check, files), and each one is checked for:
 *
 *   1. balanced paired tags - a stray closing tag escapes the pool table
 *      from its .wrap container and quietly turns it full-bleed
 *   2. the ids its script depends on
 *   3. every i18n key it references existing in both dictionaries
 *   4. no duplicate ids - a second id= robs the first element's lookups
 *   5. the bundles it reads carrying the fields the script reads
 *
 * Plus site-wide: the [hidden] rule that keeps hidden toggles hidden.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SITE = path.join(root, 'site');

const PAGES = ['index.html', 'benchmark.html', 'check.html', 'files.html'];

const TAGS = [
  'div',
  'section',
  'table',
  'thead',
  'tbody',
  'tr',
  'main',
  'header',
  'footer',
  'aside',
  'nav',
  'form',
  'p',
  'dl',
  'select',
  'label',
  'span',
  'h1',
  'h2',
  'h3',
];

// ids the page's script reads; a missing one fails at runtime, not at build
const PAGE_IDS = {
  'index.html': [
    'tbody',
    'skeleton',
    'q',
    'country',
    'per-page',
    'proto-chips',
    'grade-chips',
    'pager-info',
    'prev',
    'next',
    'empty',
    'reset-filters',
    'copy-best',
    'export-txt',
    'density',
    'drawer',
    'drawer-dl',
    'drawer-gauges',
    'drawer-title',
    'drawer-proto',
    'drawer-copy-line',
    'drawer-copy-json',
    'drawer-curl',
    'theme-toggle',
    'hero-live-text',
    'stat-alive',
    'stat-sources',
    'stat-countries',
    'stat-latency',
    'hist',
    'hist-legend',
    'segbar',
    'grade-legend',
    'comp-latency-hint',
    'pool-summary',
    'footer-meta',
    'tm-slider',
    'tm-play',
    'tm-reset',
    'toast',
  ],
  'benchmark.html': [
    'bench-body',
    'bench-q',
    'bench-sort',
    'bench-export',
    'bench-foot',
    'footer-meta',
    'theme-toggle',
    'toast',
  ],
  'check.html': ['check-input', 'check-run', 'check-result', 'footer-meta', 'theme-toggle', 'toast'],
  'files.html': ['filelist-protos', 'filelist-countries', 'sources-list', 'footer-meta', 'theme-toggle', 'toast'],
};

// the pool table must sit inside the .wrap of its section: a nesting break
// would let it escape the container and go full-bleed
const TABLE_PAGE = 'index.html';

let bad = 0;
const fail = (msg) => {
  console.error(msg);
  bad++;
};

/* dictionaries, shared by every page check */
const i18nSrc = fs.readFileSync(path.join(SITE, 'assets', 'js', 'i18n.js'), 'utf8');
const dictStart = i18nSrc.indexOf('const DICT = {');
const dictBody = dictStart >= 0 ? i18nSrc.slice(dictStart) : '';
const dictionaries = {};
if (dictBody) {
  for (const langMatch of dictBody.matchAll(/^\s+(en|ru):\s*\{([\s\S]*?)^\s+\},/gm)) {
    dictionaries[langMatch[1]] = new Set([...langMatch[2].matchAll(/'([^']+)':/g)].map((m) => m[1]));
  }
}
if (Object.keys(dictionaries).length < 2) fail('could not read the en/ru dictionaries from i18n.js');

const jsDir = path.join(SITE, 'assets', 'js');
const jsFiles = fs.existsSync(jsDir) ? fs.readdirSync(jsDir).filter((f) => f.endsWith('.js')) : [];
const jsSrc = jsFiles.map((f) => fs.readFileSync(path.join(jsDir, f), 'utf8')).join('\n');

/** all keys any page or script references */
const referenced = new Set();
for (const page of PAGES) {
  const html = fs.existsSync(path.join(SITE, page)) ? fs.readFileSync(path.join(SITE, page), 'utf8') : '';
  for (const m of html.matchAll(/data-i18n="([^"]+)"/g)) referenced.add(m[1]);
  for (const m of html.matchAll(/data-i18n-attr="([^"]+)"/g)) {
    for (const pair of m[1].split(',')) referenced.add(pair.split(':')[1]?.trim());
  }
}
for (const src of [i18nSrc, jsSrc]) {
  for (const m of src.matchAll(/\bt\('([^']+)'/g)) referenced.add(m[1]);
}
for (const [lang, keys] of Object.entries(dictionaries)) {
  for (const key of referenced) {
    if (key && !keys.has(key)) fail(`i18n key "${key}" missing from the ${lang} dictionary`);
  }
}

for (const page of PAGES) {
  const file = path.join(SITE, page);
  if (!fs.existsSync(file)) {
    fail(`missing page: site/${page}`);
    continue;
  }
  const html = fs.readFileSync(file, 'utf8');

  // paired tags must balance
  for (const tag of TAGS) {
    const open = (html.match(new RegExp(`<${tag}(?=[\\s>])`, 'g')) || []).length;
    const close = (html.match(new RegExp(`</${tag}>`, 'g')) || []).length;
    if (open !== close) fail(`${page}: unbalanced <${tag}>: ${open} open, ${close} close`);
  }

  // ids the script depends on
  for (const id of PAGE_IDS[page] ?? []) {
    if (!html.includes(`id="${id}"`)) fail(`${page}: missing element #${id}`);
  }

  // a duplicated id silently steals every lookup from the first element
  const idCounts = new Map();
  for (const m of html.matchAll(/\sid="([^"]+)"/g)) idCounts.set(m[1], (idCounts.get(m[1]) ?? 0) + 1);
  for (const [id, n] of idCounts) {
    if (n > 1) fail(`${page}: duplicate id="${id}" appears ${n} times`);
  }

  // the nav must point at real pages and mark the current one
  for (const m of html.matchAll(/<a href="([a-z]+\.html)" data-i18n="([^"]+)"/g)) {
    if (!PAGES.includes(m[1])) fail(`${page}: nav links to a page that does not exist: ${m[1]}`);
  }
  if (!html.includes('aria-current="page"'))
    fail(`${page}: no active nav entry - mark the current page with aria-current`);

  // the pool table's container, on the page that has the table
  if (page === TABLE_PAGE) {
    const poolIndex = html.indexOf('id="pool"');
    const tableIndex = html.indexOf('class="table-card"');
    if (tableIndex < 0) fail(`${page}: table-card not found`);
    if (poolIndex < 0 || poolIndex > tableIndex) {
      fail(`${page}: the pool section does not precede its table`);
    } else {
      const poolBlock = html.slice(poolIndex, tableIndex);
      if (!/class="[^"]*\bwrap\b[^"]*"/.test(poolBlock)) {
        fail(`${page}: the pool table has no .wrap container before it`);
      }
    }
  }
}

/* bundles: the app reads these fields, the build must write them */
const BUILD_FIELDS = {
  'site/data/meta.json': [
    'generatedIso',
    'total',
    'byProtocol',
    'medianLatencyMs',
    'p95LatencyMs',
    'countries',
    'sourcesOk',
    'sourcesTotal',
    'history',
    'benchmark',
  ],
  'site/data/proxies.json': [
    'id',
    'host',
    'port',
    'protocol',
    'grade',
    'latency',
    'uptime7d',
    'country',
    'exitIp',
    'mitm',
    'lastOk',
    'sources',
  ],
};
for (const [file, fields] of Object.entries(BUILD_FIELDS)) {
  const full = path.join(root, file);
  if (!fs.existsSync(full)) {
    fail(`${file} not built — run node scripts/build-web-data.mjs`);
    continue;
  }
  const data = JSON.parse(fs.readFileSync(full, 'utf8'));
  const sample = Array.isArray(data) ? data[0] : null;
  for (const field of fields) {
    const present = sample ? field in sample : field in data;
    if (!present) fail(`${file} is missing "${field}"`);
  }
}
const metaSrc = JSON.parse(fs.readFileSync(path.join(root, 'site/data/meta.json'), 'utf8'));
for (const field of ['id', 'candidates', 'alive', 'liveRate']) {
  const row = metaSrc.benchmark?.sources?.[0] ?? {};
  if (!(field in row)) fail(`meta.benchmark rows are missing "${field}"`);
}

/* the hidden attribute must beat every class display rule */
const css = fs.readFileSync(path.join(SITE, 'assets', 'css', 'main.css'), 'utf8');
if (!/\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(css)) {
  fail('main.css is missing the global [hidden]{display:none!important} rule — hidden toggles will be overridden');
}

if (bad) {
  console.error(`site structure check FAILED (${bad} problems)`);
  process.exit(1);
}
console.log(`site structure ok (${PAGES.length} pages)`);
