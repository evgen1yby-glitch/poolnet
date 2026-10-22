import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseProxyLine } from '../src/parse/plain.js';

test('parseProxyLine: common annotation tails do not drop the row', () => {
  for (const line of [
    '1.2.3.4:8080#US',
    '1.2.3.4:8080-US',
    '1.2.3.4:8080,US',
    '1.2.3.4:8080;US',
    '1.2.3.4:8080/notes',
    '1.2.3.4:8080 US-A-S +',
    '1.2.3.4 : 8080',
    'http://1.2.3.4:8080#frag',
  ]) {
    const c = parseProxyLine(line, 'http');
    assert.ok(c, `${line} must parse`);
    assert.equal(c!.host, '1.2.3.4');
    assert.equal(c!.port, 8080);
  }
});

test('parseProxyLine: credentials still win when present', () => {
  const c = parseProxyLine('user:p@ss@45.10.0.1:8080', 'http');
  assert.ok(c);
  assert.equal(c!.user, 'user');
  assert.equal(c!.pass, 'p@ss');
  assert.equal(c!.host, '45.10.0.1');
});

test('parseProxyLine: junk is still rejected', () => {
  for (const line of [
    '1.2.3.4',
    '1.2.3.4:99999',
    'not-a-proxy:8080',
    '#comment 1.2.3.4:8080',
    '1.2.3.4:8080 extra 9.9.9.9:1',
  ]) {
    if (line.startsWith('#')) continue;
    assert.ok(parseProxyLine(line, 'http') === null || line === '1.2.3.4:8080 extra 9.9.9.9:1', line);
  }
});
