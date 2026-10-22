import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isUsableIPv4, normalizeIPv4 } from '../src/sources/types.js';
import { parseProxyLine } from '../src/parse/plain.js';

test('isUsableIPv4: rejects private, CGNAT, link-local, test and broadcast ranges', () => {
  for (const bad of [
    '0.0.0.0',
    '10.0.0.1',
    '100.64.0.1',
    '127.0.0.1',
    '169.254.1.1',
    '172.16.0.1',
    '172.31.255.255',
    '192.168.1.1',
    '192.0.2.5',
    '198.18.0.1',
    '198.51.100.7',
    '203.0.113.9',
    '224.0.0.1',
    '255.255.255.255',
  ]) {
    assert.equal(isUsableIPv4(bad), false, `${bad} must be rejected`);
  }
  for (const ok of ['1.1.1.1', '8.8.8.8', '172.15.0.1', '172.32.0.1', '192.0.1.1', '223.255.255.255']) {
    assert.equal(isUsableIPv4(ok), true, `${ok} must be usable`);
  }
});

test('normalizeIPv4: leading zeros collapse to the same host', () => {
  assert.equal(normalizeIPv4('010.1.1.1'), '10.1.1.1');
  assert.equal(normalizeIPv4('010.000.1.1'), '10.0.1.1');
  assert.equal(normalizeIPv4('1.2.3.4'), '1.2.3.4');
});

test('parseProxyLine: leading-zero hosts are normalized on the way in', () => {
  const c = parseProxyLine('045.084.013.153:8080', 'http');
  assert.ok(c);
  assert.equal(c!.host, '45.84.13.153');
  assert.equal(parseProxyLine('45.84.13.153:8080', 'http')!.host, '45.84.13.153');
  // the same host written two ways must produce one identity
  assert.deepEqual(c, parseProxyLine('45.84.13.153:8080', 'http'));
});

test('parseProxyLine: private addresses never enter the pipeline', () => {
  for (const line of ['10.0.0.1:8080', '192.168.1.1:3128', '127.0.0.1:8080', '169.254.169.254:80']) {
    assert.equal(parseProxyLine(line, 'http'), null, `${line} must be rejected`);
  }
});
