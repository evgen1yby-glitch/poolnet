import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRoundproxies } from '../src/parse/roundproxies.js';

const row = (addr: string, port: string, rest: string) => `<tr><td>${addr}</td><td>${port}</td>${rest}</tr>`;

const HTML = `<table><tbody>
${row('45.84.13.153', '1080', '<td>1 / 1</td><td>RU</td><td>285.00ms</td><td>socks5</td><td>100+</td><td>50+</td><td>OOO Kurier</td><td>95.4%</td><td></td><td>elite</td>')}
${row('115.74.153.148', '1080', '<td>2 / 3</td><td>VN</td><td>1200ms</td><td>socks4</td><td>10+</td><td>5+</td><td>Viettel</td><td>61%</td><td></td><td>anonymous</td>')}
${row('8.8.8.8', '80', '<td>0 / 2</td><td>US</td><td></td><td>http</td><td></td><td></td><td>Google</td><td></td><td></td><td></td>')}
${row('127.0.0.1', '9999', '<td></td><td>XX</td><td></td><td>socks5</td>')}
</tbody></table>`;

test('parseRoundproxies: extracts rows with their claims', () => {
  const out = parseRoundproxies(HTML, 'http');
  assert.equal(out.length, 3);
  assert.deepEqual(out[0], { protocol: 'socks5', host: '45.84.13.153', port: 1080, source: '', country: 'RU' });
  assert.equal(out[1]!.protocol, 'socks4');
  assert.equal(out[1]!.country, 'VN');
  assert.equal(out[2]!.protocol, 'http');
});

test('parseRoundproxies: falls back to the declared protocol', () => {
  const out = parseRoundproxies(row('9.9.9.9', '3128', '<td>0 / 1</td>'), 'socks5');
  assert.equal(out.length, 1);
  assert.equal(out[0]!.protocol, 'socks5');
});

test('parseRoundproxies: rejects private addresses and junk', () => {
  assert.equal(parseRoundproxies('<table><tbody><tr><td>nope</td></tr></tbody></table>', 'http').length, 0);
  assert.equal(parseRoundproxies('', 'http').length, 0);
  assert.equal(parseRoundproxies(row('127.0.0.1', '9999', ''), 'http').length, 0);
});
