import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseAdvancedName } from '../src/parse/advancedname.js';

// Shape captured from the live page: base64 attributes, type as an anchor
// with a ?type= query, country from the flag class.
const HTML = `<table><tbody><tr>
<td>1</td><td data-ip="NDcuODUuMTMuMTk4"></td><td data-port="MTA4MA=="></td>
<td><a href="https://advanced.name/freeproxy?type=socks4" class="label label-success">SOCKS4</a></td>
<td><img class="flag-free flag-free-us" src="/img/flags/blank.png" alt="Free Proxy US"><a href="?country=us">US</a></td>
</tr><tr>
<td>2</td><td data-ip="MTAzLjU1LjYzLjE0"></td><td data-port="MTA4MA=="></td>
<td><a href="/freeproxy?type=socks5" class="label label-success">SOCKS5</a></td>
<td><img class="flag-free flag-free-in" src="/img/flags/blank.png"><a href="?country=in">IN</a></td>
</tr><tr>
<td>3</td><td data-ip="MS4yLjMuNA=="></td><td data-port="ODA="></td>
<td><a href="/freeproxy?type=http" class="label">HTTP</a></td>
<td><img class="flag-free flag-free-de"></td>
</tr></tbody></table>`;

test('parseAdvancedName: decodes base64 address/port and claims', () => {
  const out = parseAdvancedName(HTML, 'http');
  assert.equal(out.length, 3);
  assert.deepEqual(out[0], { protocol: 'socks4', host: '47.85.13.198', port: 1080, source: '', country: 'US' });
  assert.deepEqual(out[1], { protocol: 'socks5', host: '103.55.63.14', port: 1080, source: '', country: 'IN' });
  assert.equal(out[2]!.protocol, 'http');
  assert.equal(out[2]!.port, 80);
  assert.equal(out[2]!.country, 'DE');
});

test('parseAdvancedName: falls back to the declared protocol', () => {
  const noType = `<table><tbody><tr>
<td>1</td><td data-ip="NDcuODUuMTMuMTk4"></td><td data-port="MTA4MA=="></td>
<td>unknown</td><td>unknown</td>
</tr></tbody></table>`;
  const out = parseAdvancedName(noType, 'socks5');
  assert.equal(out.length, 1);
  assert.equal(out[0]!.protocol, 'socks5');
});

test('parseAdvancedName: rejects junk payloads', () => {
  assert.equal(parseAdvancedName('<html>nothing</html>', 'http').length, 0);
  assert.equal(parseAdvancedName('', 'http').length, 0);
  // invalid base64 or private addresses yield nothing
  const bad = HTML.replace('NDcuODUuMTMuMTk4', '!!!notbase64!!!').replace('MTAzLjU1LjYzLjE0', 'MTI3LjAuMC4x');
  assert.equal(parseAdvancedName(bad, 'http').length, 1, 'only the third row survives');
});
