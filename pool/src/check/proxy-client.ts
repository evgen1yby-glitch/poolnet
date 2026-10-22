import net from 'node:net';
import { NET_CHECK } from './errors.js';
import { SocketReader, tcpConnect } from './net.js';

/** A proxy to route through. */
export interface ProxyTarget {
  protocol: 'http' | 'socks4' | 'socks5';
  host: string;
  port: number;
  user?: string;
  pass?: string;
}

const CRLF = '\r\n';

export interface Connection {
  sock: net.Socket;
  /** the reader that consumed the handshake; detach() before using the socket */
  reader: SocketReader;
}

/**
 * Open a raw TCP connection to `destHost:destPort` through the proxy.
 * For socks5 the handshake completes through CONNECT; no payload is sent.
 */
export async function connectThrough(
  proxy: ProxyTarget,
  destHost: string,
  destPort: number,
  timeoutMs: number,
): Promise<Connection> {
  if (proxy.protocol === 'socks5') return socks5Connect(proxy, destHost, destPort, timeoutMs);
  if (proxy.protocol === 'socks4') return socks4Connect(proxy, destHost, destPort, timeoutMs);
  return httpConnect(proxy, destHost, destPort, timeoutMs);
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new NET_CHECK(`timeout: ${what}`)), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}

/** One buffered reader per socket, attached at connect time. */
function attachReader(sock: net.Socket): SocketReader {
  return new SocketReader(sock);
}

async function socks5Connect(
  proxy: ProxyTarget,
  destHost: string,
  destPort: number,
  timeoutMs: number,
): Promise<Connection> {
  const sock = await tcpConnect(proxy.host, proxy.port, timeoutMs);
  const reader = attachReader(sock);
  const done = (async () => {
    const methods = proxy.user && proxy.pass ? Buffer.from([0x05, 0x02, 0x00, 0x02]) : Buffer.from([0x05, 0x01, 0x00]);
    sock.write(methods);
    const greet = await reader.readN(2, timeoutMs);
    if (greet[0] !== 0x05) throw new NET_CHECK('socks5: bad greeting version');
    const method = greet[1]!;
    if (method === 0xff) throw new NET_CHECK('socks5: no acceptable auth method');

    if (method === 0x02) {
      const u = Buffer.from(proxy.user ?? '', 'utf8');
      const p = Buffer.from(proxy.pass ?? '', 'utf8');
      sock.write(Buffer.concat([Buffer.from([0x01, u.length]), u, Buffer.from([p.length]), p]));
      const auth = await reader.readN(2, timeoutMs);
      if (auth[1] !== 0x00) throw new NET_CHECK('socks5: auth rejected');
    }

    sock.write(connectRequest(destHost, destPort));
    const head = await reader.readN(4, timeoutMs);
    if (head[1] !== 0x00) throw new NET_CHECK(`socks5: connect refused (rep=${head[1]})`);
    const atyp = head[3]!;
    let addrLen = 0;
    if (atyp === 0x01) addrLen = 4;
    else if (atyp === 0x03) {
      const len = await reader.readN(1, timeoutMs);
      addrLen = len[0]!;
    } else if (atyp === 0x04) addrLen = 16;
    else throw new NET_CHECK('socks5: bad reply atyp');
    await reader.readN(addrLen + 2, timeoutMs);
    return { sock, reader };
  })();

  try {
    return await withTimeout(done, timeoutMs, `socks5 ${proxy.host}:${proxy.port}`);
  } catch (e) {
    sock.destroy();
    throw e;
  }
}

function connectRequest(destHost: string, destPort: number): Buffer {
  const parts: Buffer[] = [Buffer.from([0x05, 0x01, 0x00])];
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(destHost);
  if (ipv4) {
    parts.push(Buffer.from([0x01]), Buffer.from(ipv4.slice(1).map(Number)));
  } else {
    const d = Buffer.from(destHost, 'utf8');
    parts.push(Buffer.from([0x03, d.length]), d);
  }
  parts.push(Buffer.from([(destPort >> 8) & 0xff, destPort & 0xff]));
  return Buffer.concat(parts);
}

async function socks4Connect(
  proxy: ProxyTarget,
  destHost: string,
  destPort: number,
  timeoutMs: number,
): Promise<Connection> {
  const sock = await tcpConnect(proxy.host, proxy.port, timeoutMs);
  const reader = attachReader(sock);
  const done = (async () => {
    const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(destHost);
    if (!ipv4) throw new NET_CHECK('socks4: only IPv4 destinations supported');
    const user = Buffer.from(proxy.user ?? 'x', 'utf8');
    sock.write(
      Buffer.concat([
        Buffer.from([0x04, 0x01, (destPort >> 8) & 0xff, destPort & 0xff]),
        Buffer.from(ipv4.slice(1).map(Number)),
        user,
        Buffer.from([0x00]),
      ]),
    );
    const rep = await reader.readN(8, timeoutMs);
    if (rep[1] !== 0x5a) throw new NET_CHECK(`socks4: refused (rep=${rep[1]})`);
    return { sock, reader };
  })();
  try {
    return await withTimeout(done, timeoutMs, `socks4 ${proxy.host}:${proxy.port}`);
  } catch (e) {
    sock.destroy();
    throw e;
  }
}

async function httpConnect(
  proxy: ProxyTarget,
  destHost: string,
  destPort: number,
  timeoutMs: number,
): Promise<Connection> {
  const sock = await tcpConnect(proxy.host, proxy.port, timeoutMs);
  const reader = attachReader(sock);
  const done = (async () => {
    const target = `${destHost}:${destPort}`;
    let head = `CONNECT ${target} HTTP/1.1${CRLF}Host: ${target}${CRLF}`;
    if (proxy.user && proxy.pass) {
      const cred = Buffer.from(`${proxy.user}:${proxy.pass}`, 'utf8').toString('base64');
      head += `Proxy-Authorization: Basic ${cred}${CRLF}`;
    }
    head += `Connection: keep-alive${CRLF}${CRLF}`;
    sock.write(head);
    const line = (await reader.readUntil('\n', timeoutMs)).toString('latin1').replace(/\r$/, '');
    const m = /^HTTP\/1\.[01] (\d{3})/.exec(line);
    if (!m) throw new NET_CHECK('http proxy: malformed status line');
    const status = Number(m[1]);
    if (status !== 200) throw new NET_CHECK(`http proxy: CONNECT -> ${status}`);
    for (;;) {
      const h = (await reader.readUntil('\n', timeoutMs)).toString('latin1').replace(/\r$/, '');
      if (h === '') break;
    }
    return { sock, reader };
  })();
  try {
    return await withTimeout(done, timeoutMs, `http ${proxy.host}:${proxy.port}`);
  } catch (e) {
    sock.destroy();
    throw e;
  }
}
