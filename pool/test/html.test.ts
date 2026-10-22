import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseHtmlSource } from '../src/parse/html.js';

test('parseHtmlSource: extracts ip:port from an embedded text block', () => {
  const html = `<html><body><textarea>1.2.3.4:8080\n5.6.7.8:3128\nbogus\n</textarea></body></html>`;
  const out = parseHtmlSource(html, 'http');
  assert.deepEqual(out, [
    { protocol: 'http', host: '1.2.3.4', port: 8080, source: '' },
    { protocol: 'http', host: '5.6.7.8', port: 3128, source: '' },
  ]);
});

test('parseHtmlSource: pairs adjacent table cells when no colons are present', () => {
  const html = `<table><tr><td>1.2.3.4</td><td>8080</td></tr><tr><td>5.6.7.8</td><td>1080</td></tr></table>`;
  const out = parseHtmlSource(html, 'socks5');
  assert.equal(out.length, 2);
  assert.equal(out[0]!.host, '1.2.3.4');
  assert.equal(out[0]!.port, 8080);
  assert.equal(out[1]!.protocol, 'socks5');
});

test('parseHtmlSource: rejects junk and private ranges', () => {
  const html = `<p>999.1.1.1:80</p><p>127.0.0.1:8080</p><p>0.0.0.0:80</p>`;
  assert.equal(parseHtmlSource(html, 'http').length, 0);
});
