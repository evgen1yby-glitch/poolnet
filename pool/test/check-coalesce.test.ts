import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { checkProxy } from '../src/check/stage.js';
import type { EchoTarget } from '../src/check/errors.js';

/**
 * A SOCKS5 proxy that pipelines: the CONNECT reply and the whole target
 * response arrive in one TCP segment. Proxies of this shape used to be
 * reported dead because the response bytes were consumed by the handshake
 * reader and never reached the HTTP reader.
 */
function startCoalescingProxy(response: string): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((sock) => {
    let stage = 0;
    sock.on('error', () => sock.destroy());
    sock.on('data', (_d) => {
      if (stage === 0) {
        sock.write(Buffer.from([0x05, 0x00]));
        stage = 1;
        return;
      }
      if (stage === 1) {
        const reply = Buffer.from([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]);
        // one write: handshake reply + a complete HTTP response, and nothing
        // else afterwards - the request that follows must be served from
        // these bytes alone, exactly like a proxy that pipelines hard
        sock.write(Buffer.concat([reply, Buffer.from(response, 'latin1')]));
        stage = 2;
        return;
      }
      // the GET that follows gets no re-send: answering it again would hide
      // the lost bytes this regression test exists to catch
      return;
    });
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () =>
      resolve({
        port: (server.address() as net.AddressInfo).port,
        close: () => new Promise<void>((r) => server.close(() => r())),
      }),
    );
  });
}

const ECHO = (body: string) =>
  `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`;

test('checkProxy: a coalesced CONNECT reply + response is alive, not dead', async () => {
  const body = JSON.stringify({ origin: '203.0.113.9', headers: {} });
  const proxy = await startCoalescingProxy(ECHO(body));
  const targets: EchoTarget[] = [{ url: 'http://127.0.0.1:1/get', parser: 'json', label: 'mock' }];
  try {
    const out = await checkProxy(
      { protocol: 'socks5', host: '127.0.0.1', port: proxy.port },
      { timeoutMs: 5000, stage1TimeoutMs: 3000, targets },
    );
    assert.equal(out.alive, true, `a pipelined reply must not read as an empty response: ${out.error}`);
    assert.equal(out.remoteIp, '203.0.113.9');
  } finally {
    await proxy.close();
  }
});
