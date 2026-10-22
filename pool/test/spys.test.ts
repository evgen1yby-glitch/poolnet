import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseSpys } from '../src/parse/spys.js';

const root = path.dirname(fileURLToPath(import.meta.url));
const LIVE = fs.readFileSync(path.join(root, 'fixtures', 'spys-sample.html'), 'utf8');

test('parseSpys: decodes ports from a real captured page', () => {
  const out = parseSpys(LIVE, 'http');
  assert.equal(out.length, 2);
  for (const e of out) {
    assert.ok(Number.isInteger(e.port) && e.port >= 1 && e.port <= 65535, `port was ${e.port}`);
    assert.ok(/^\d+\.\d+\.\d+\.\d+$/.test(e.host));
  }
  // the source claims HTTP for this page; types come through as claims
  for (const e of out) assert.ok(['http', 'socks4', 'socks5'].includes(e.protocol));
});

test('parseSpys: the fixture is stable across runs', () => {
  const a = parseSpys(LIVE, 'http');
  const b = parseSpys(LIVE, 'http');
  assert.deepEqual(a, b);
});

test('parseSpys: drops private addresses', () => {
  const withPrivate = LIVE.replace(/<font class=spy14>\d+\.\d+\.\d+\.\d+/, '<font class=spy14>127.0.0.1');
  const out = parseSpys(withPrivate, 'http');
  assert.equal(out.length, 1);
  assert.notEqual(out[0]!.host, '127.0.0.1');
});

test('parseSpys: unparseable input yields nothing', () => {
  assert.equal(parseSpys('<html>no table here</html>', 'http').length, 0);
  assert.equal(parseSpys('', 'http').length, 0);
  assert.equal(parseSpys('not json at all', 'http').length, 0);
});

test('parseSpys: a decoy document.write elsewhere cannot shift the pairing', () => {
  // a script tag at the top of the page emitting a port-shaped string used to
  // move every subsequent row onto the previous row's port
  const decoy = LIVE.replace('<table>', '<script>document.write(":443")</script><table>');
  const out = parseSpys(decoy, 'http');
  assert.equal(out.length, 2);
  assert.deepEqual(
    out.map((e) => e.port),
    [80, 8080],
  );
});

test('parseSpys: an unmatched row loses only itself, not its neighbour', () => {
  // one row's class changes so IP_ROW_RE skips it, while its write stays in
  // the page: the surviving row must keep its own port
  const broken = LIVE.replace('<font class=spy14>112.198.22.122', '<font class=spy1x>112.198.22.122');
  const out = parseSpys(broken, 'http');
  assert.equal(out.length, 1);
  assert.equal(out[0]!.host, '131.196.50.128');
  assert.equal(out[0]!.port, 8080);
});

test('parseSpys: the type claim comes through on the mixed page', () => {
  const out = parseSpys(LIVE, 'http');
  assert.equal(out[0]!.claim.type, 'HTTP');
  assert.equal(out[1]!.claim.type, 'HTTPS', 'the anchor-wrapped type cell must be read');
});
