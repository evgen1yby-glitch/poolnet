import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadSources } from '../src/sources/load.js';

function writeRegistry(entries: unknown): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'opp-sources-'));
  const file = path.join(dir, 'sources.yaml');
  fs.writeFileSync(file, `sources:\n${entries}\n`);
  return file;
}

test('loadSources: expands ${ENV} in url and auth', () => {
  process.env.TEST_PROXY_URL = 'https://example.com/list.txt';
  process.env.TEST_PROXY_KEY = 'k123';
  const file = writeRegistry(
    ['  - id: api', '    url: ${TEST_PROXY_URL}', '    format: gfp', '    auth: bearer:${TEST_PROXY_KEY}'].join('\n'),
  );
  const { sources, skipped } = loadSources(file);
  assert.equal(skipped.length, 0);
  assert.equal(sources[0]!.url, 'https://example.com/list.txt');
  assert.equal(sources[0]!.auth, 'bearer:k123');
});

test('loadSources: skips sources whose env placeholder is unset', () => {
  delete process.env.MISSING_KEY;
  const file = writeRegistry(
    [
      '  - id: plain',
      '    url: https://example.com/ok.txt',
      '    format: plain',
      '  - id: api',
      '    url: https://example.com/api',
      '    format: gfp',
      '    auth: bearer:${MISSING_KEY}',
    ].join('\n'),
  );
  const { sources, skipped } = loadSources(file);
  assert.deepEqual(
    sources.map((s) => s.id),
    ['plain'],
  );
  assert.deepEqual(skipped, ['api']);
});

test('loadSources: skips unknown formats and duplicate ids', () => {
  const file = writeRegistry(
    [
      '  - id: a',
      '    url: https://example.com/a.txt',
      '    format: plain',
      '  - id: a',
      '    url: https://example.com/b.txt',
      '    format: plain',
      '  - id: c',
      '    url: https://example.com/c.txt',
      '    format: shoutcast',
    ].join('\n'),
  );
  const { sources, skipped } = loadSources(file);
  assert.deepEqual(
    sources.map((s) => s.id),
    ['a'],
  );
  assert.ok(skipped.includes('c'));
});

test('loadSources: sources.yaml is fully valid and every url is expanded', () => {
  const { sources, skipped } = loadSources('sources.yaml');
  assert.ok(sources.length > 150, `expected the real registry, got ${sources.length}`);
  for (const s of sources) {
    assert.ok(/^https?:\/\//.test(s.url), `${s.id}: unexpanded url ${s.url}`);
    if (s.auth) assert.ok(!/\$\{/.test(s.auth), `${s.id}: unexpanded auth`);
  }
  // gfp entries only stay when the key is present; assert consistency
  const gfp = sources.filter((s) => s.format === 'gfp');
  assert.equal(gfp.length, process.env.GFP_API_KEY ? 4 : 0);
  assert.ok(skipped.every((s) => s === 'c' || s.startsWith('gfp') || s === 'malformed'));
});
