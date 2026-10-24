import net from 'node:net';

/** Local echo server: returns { origin, headers } like httpbingo/get. */
export function startEchoServer(
  port: number,
  opts: { injectHeaders?: Record<string, string> } = {},
): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((sock) => {
    let buf = Buffer.alloc(0);
    sock.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      const idx = buf.indexOf('\r\n\r\n');
      if (idx < 0) return;
      const head = buf.subarray(0, idx).toString('latin1');
      const m = /^GET (\S+) HTTP\/1\.[01]/.exec(head);
      if (!m) {
        sock.end('HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n');
        return;
      }
      const inbound: Record<string, string> = {};
      for (const line of head.split('\r\n').slice(1)) {
        const c = line.indexOf(':');
        if (c > 0) inbound[line.slice(0, c).trim().toLowerCase()] = line.slice(c + 1).trim();
      }
      if (opts.injectHeaders) Object.assign(inbound, opts.injectHeaders);
      const body = JSON.stringify({ origin: sock.remoteAddress, headers: inbound });
      sock.end(
        `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`,
      );
      buf = Buffer.alloc(0);
    });
    sock.on('error', () => sock.destroy());
  });
  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () =>
      resolve({
        port: (server.address() as net.AddressInfo).port,
        close: () => new Promise<void>((r) => server.close(() => r())),
      }),
    );
  });
}

/**
 * A plain web server (CDN-like) that answers any Host and refuses CONNECT.
 * If a checker ever falls back to an absolute-form GET, this host would look
 * like a working proxy even though it never forwarded anything.
 */
export function startFakeCdnServer(): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((sock) => {
    let buf = Buffer.alloc(0);
    sock.on('error', () => sock.destroy());
    sock.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      const idx = buf.indexOf('\r\n\r\n');
      if (idx < 0) return;
      const first = buf.subarray(0, idx).toString('latin1').split('\r\n')[0] ?? '';
      if (/^CONNECT /i.test(first)) {
        sock.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');
      } else {
        const body = JSON.stringify({ origin: '203.0.113.9', headers: { 'x-forwarded-for': '203.0.113.9' } });
        sock.end(
          `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`,
        );
      }
      buf = Buffer.alloc(0);
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

/**
 * A real HTTP CONNECT proxy: completes the tunnel and pipes bytes both ways.
 * Used to prove that removing the absolute-form fallback did not break
 * legitimate HTTP proxies.
 */
export function startHttpProxyServer(): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((client) => {
    let buf = Buffer.alloc(0);
    let upstream: net.Socket | null = null;
    client.on('error', () => client.destroy());
    client.on('data', (d) => {
      if (upstream) {
        upstream.write(d);
        return;
      }
      buf = Buffer.concat([buf, d]);
      const idx = buf.indexOf('\r\n\r\n');
      if (idx < 0) return;
      const head = buf.subarray(0, idx).toString('latin1');
      const first = head.split('\r\n')[0] ?? '';
      const m = /^CONNECT (\S+):(\d+) HTTP\/1\.[01]/.exec(first);
      if (!m) {
        client.end('HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n');
        return;
      }
      const host = m[1]!;
      const port = Number(m[2]);
      const rest = buf.subarray(idx + 4);
      buf = Buffer.alloc(0);
      upstream = net.connect(port, host, () => {
        client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        if (rest.length) upstream?.write(rest);
      });
      upstream.on('data', (chunk) => client.write(chunk));
      upstream.on('error', () => client.destroy());
      upstream.on('close', () => client.destroy());
      client.on('close', () => upstream?.destroy());
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

/**
 * Accepts CONNECT but answers with its own fake JSON instead of tunneling.
 * The missing per-request nonce must make the check fail.
 */
export function startFakeConnectProxy(): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((sock) => {
    let buf = Buffer.alloc(0);
    sock.on('error', () => sock.destroy());
    sock.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      const idx = buf.indexOf('\r\n\r\n');
      if (idx < 0) return;
      const body = JSON.stringify({ origin: '203.0.113.10', headers: {} });
      sock.end(
        `HTTP/1.1 200 Connection Established\r\n\r\n` +
          `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`,
      );
      buf = Buffer.alloc(0);
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

/**
 * Minimal local SOCKS5 proxy. `injectHeaders` are added to requests it
 * forwards, which lets tests simulate transparent/anonymous proxies.
 */
export function startSocks5Server(
  opts: { injectHeaders?: Record<string, string>; requireAuth?: boolean } = {},
): Promise<{ port: number; close: () => Promise<void> }> {
  const server = net.createServer((client) => {
    let stage = 0;
    let authed = !opts.requireAuth;
    let upstream: net.Socket | null = null;
    let forwarded = false;

    client.on('error', () => client.destroy());
    client.on('data', (d) => {
      if (stage === 0) {
        const version = d[0];
        if (version !== 0x05) return client.destroy();
        if (opts.requireAuth) {
          client.write(Buffer.from([0x05, 0x02]));
          stage = 1;
        } else {
          client.write(Buffer.from([0x05, 0x00]));
          stage = 2;
        }
        return;
      }
      if (stage === 1 && !authed) {
        // 0x01 ulen user plen pass
        const ulen = d[1]!;
        const plen = d[2 + ulen]!;
        client.write(Buffer.from([0x01, 0x00]));
        authed = true;
        stage = 2;
        void plen;
        return;
      }
      if (stage === 2) {
        // parse CONNECT (atyp 1 or 3)
        const atyp = d[3]!;
        let destHost: string;
        let off: number;
        if (atyp === 0x01) {
          destHost = `${d[4]}.${d[5]}.${d[6]}.${d[7]}`;
          off = 8;
        } else if (atyp === 0x03) {
          const len = d[4]!;
          destHost = d.subarray(5, 5 + len).toString();
          off = 5 + len;
        } else {
          client.write(Buffer.from([0x05, 0x08, 0x00, 0x01, 0, 0, 0, 0, 0, 0]));
          return client.destroy();
        }
        const destPort = d.readUInt16BE(off)!;
        const rest = d.subarray(off + 2);

        upstream = net.connect(destPort, destHost, () => {
          client.write(Buffer.from([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]));
          if (upstream && rest.length) upstream.write(rest);
        });
        upstream.on('data', (chunk) => client.write(chunk));
        upstream.on('error', () => client.destroy());
        upstream.on('close', () => client.destroy());
        client.on('close', () => upstream?.destroy());
        stage = 3;
        return;
      }
      if (stage === 3 && upstream) {
        upstream.write(forwarded ? d : maybeInject(d));
        forwarded = true;
      }
    });

    function maybeInject(payload: Buffer): Buffer {
      if (!opts.injectHeaders) return payload;
      const head = payload.toString('latin1');
      const at = head.indexOf('\r\n');
      if (at < 0) return payload;
      const injected = Object.entries(opts.injectHeaders)
        .map(([k, v]) => `${k}: ${v}`)
        .join('\r\n');
      return Buffer.from(head.slice(0, at + 2) + injected + '\r\n' + head.slice(at + 2), 'latin1');
    }
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
