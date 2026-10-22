import { test } from 'node:test';
import assert from 'node:assert/strict';
import { issuerIsMitm } from '../src/check/stage.js';

test('issuerIsMitm: a real CA whose name contains "None" is not interception', () => {
  assert.equal(issuerIsMitm('None, LLC / None'), false);
  assert.equal(issuerIsMitm("Let's Encrypt / YE1"), false);
  assert.equal(issuerIsMitm('SSL Corporation / SSL.com'), false);
});

test('issuerIsMitm: interception tools and empty issuers are flagged', () => {
  assert.equal(issuerIsMitm('mitmproxy'), true);
  assert.equal(issuerIsMitm('Burp Suite CA'), true);
  assert.equal(issuerIsMitm(''), true);
  assert.equal(issuerIsMitm('none'), true);
  assert.equal(issuerIsMitm('(None)'), true);
});
