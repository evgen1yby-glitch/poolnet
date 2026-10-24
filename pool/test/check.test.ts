import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkProxy } from '../src/check/stage.js';
import type { EchoTarget } from '../src/check/errors.js';
import {
  startEchoServer,
  startFakeCdnServer,
  startFakeConnectProxy,
  startHttpProxyServer,
  startSocks5Server,
} from './helpers/mocks.js';

const TARGETS: EchoTarget[] = [];

async function withServers(
  injectHeaders: Record<string, string> | undefined,
  fn: (port: number, echoPort: number, targets: EchoTarget[]) => Promise<void>,
) {
  const echo = await startEchoServer(0);
  const socks = await startSocks5Server({ injectHeaders });
  const targets: EchoTarget[] = [{ url: `https://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' }];
  // The checker always speaks TLS to https targets; the mock is plain HTTP,
  // so exercise the http target path and TLS via fallback semantics.
  targets.length = 0;
  targets.push({ url: `http://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' });
  try {
    await fn(socks.port, echo.port, targets);
  } finally {
    await echo.close();
    await socks.close();
  }
}

test('checkProxy: working socks5 proxy is alive and elite', async () => {
  await withServers(undefined, async (socksPort, _echoPort, targets) => {
    const out = await checkProxy(
      { protocol: 'socks5', host: '127.0.0.1', port: socksPort },
      { timeoutMs: 5000, stage1TimeoutMs: 3000, targets },
    );
    assert.equal(out.alive, true, `error: ${out.error}`);
    assert.equal(out.stage, 'L2');
    assert.equal(out.anonymity, 'elite');
    assert.equal(out.latencyMs !== null && out.latencyMs >= 0, true);
  });
});

test('checkProxy: transparent proxy (leaks client IP via header)', async () => {
  await withServers({ 'X-Forwarded-For': '9.9.9.9' }, async (socksPort, _echoPort, targets) => {
    const out = await checkProxy(
      { protocol: 'socks5', host: '127.0.0.1', port: socksPort },
      { timeoutMs: 5000, stage1TimeoutMs: 3000, targets },
    );
    assert.equal(out.alive, true);
    assert.equal(out.anonymity, 'transparent');
  });
});

test('checkProxy: anonymous proxy (proxy header, no client IP)', async () => {
  await withServers({ Via: '1.1 mock-proxy' }, async (socksPort, _echoPort, targets) => {
    const out = await checkProxy(
      { protocol: 'socks5', host: '127.0.0.1', port: socksPort },
      { timeoutMs: 5000, stage1TimeoutMs: 3000, targets },
    );
    assert.equal(out.alive, true);
    assert.equal(out.anonymity, 'anonymous');
  });
});

test('checkProxy: a web host that answers any Host is not a proxy', async () => {
  const cdn = await startFakeCdnServer();
  const targets: EchoTarget[] = [{ url: 'http://example.com/get', parser: 'json', label: 'fake-cdn' }];
  try {
    const out = await checkProxy(
      { protocol: 'http', host: '127.0.0.1', port: cdn.port },
      { timeoutMs: 3000, stage1TimeoutMs: 1000, targets },
    );
    assert.equal(out.alive, false, 'absolute-form GET must not be accepted');
    assert.match(out.error ?? '', /CONNECT/);
  } finally {
    await cdn.close();
  }
});

test('checkProxy: a CONNECT-refusing HTTP proxy is dead', async () => {
  const proxy = await startFakeCdnServer();
  const targets: EchoTarget[] = [{ url: 'https://example.com/get', parser: 'json', label: 'fake-cdn' }];
  try {
    const out = await checkProxy(
      { protocol: 'http', host: '127.0.0.1', port: proxy.port },
      { timeoutMs: 3000, stage1TimeoutMs: 1000, targets },
    );
    assert.equal(out.alive, false);
  } finally {
    await proxy.close();
  }
});

test('checkProxy: a working HTTP proxy completes CONNECT and is graded', async () => {
  const echo = await startEchoServer(0);
  const proxy = await startHttpProxyServer();
  const targets: EchoTarget[] = [{ url: `http://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' }];
  try {
    const out = await checkProxy(
      { protocol: 'http', host: '127.0.0.1', port: proxy.port },
      { timeoutMs: 5000, stage1TimeoutMs: 3000, targets },
    );
    assert.equal(out.alive, true, `error: ${out.error}`);
    assert.equal(out.anonymity, 'elite');
  } finally {
    await echo.close();
    await proxy.close();
  }
});

test('checkProxy: a host that accepts CONNECT but does not tunnel is dead', async () => {
  const proxy = await startFakeConnectProxy();
  const targets: EchoTarget[] = [{ url: 'http://example.com/get', parser: 'json', label: 'fake-tunnel' }];
  try {
    const out = await checkProxy(
      { protocol: 'http', host: '127.0.0.1', port: proxy.port },
      { timeoutMs: 3000, stage1TimeoutMs: 1000, targets },
    );
    assert.equal(out.alive, false);
    assert.match(out.error ?? '', /nonce/);
  } finally {
    await proxy.close();
  }
});

test('checkProxy: dead port is reported dead, not thrown', async () => {
  const echo = await startEchoServer(0);
  const targets: EchoTarget[] = [{ url: `http://127.0.0.1:${echo.port}/get`, parser: 'json', label: 'mock' }];
  try {
    const out = await checkProxy(
      { protocol: 'socks5', host: '127.0.0.1', port: 1 },
      { timeoutMs: 3000, stage1TimeoutMs: 1000, targets },
    );
    assert.equal(out.alive, false);
    assert.ok(out.error);
  } finally {
    await echo.close();
  }
});

void TARGETS;
