/**
 * On-demand proxy check for the Worker (the edge counterpart of the
 * platform's check page). Everything here is pure and stream-based so the
 * same code runs in
 * workerd (real sockets) and in Node tests (a stub socket).
 *
 * The check answers one question a visitor actually has: "does this thing
 * work?" - a full liveness probe through the proxy, plus the origin address
 * the target saw, which is what makes the answer trustworthy.
 */

/** @typedef {{ protocol: 'http'|'socks4'|'socks5', host: string, port: number }} CheckRequest */

/** @typedef {{ writable: WritableStream<Uint8Array>, readable: ReadableStream<Uint8Array>, close(): Promise<void> }} SocketLike */

/** @typedef {{ proxy: CheckRequest, connect: (opts: { hostname: string, port: number }) => SocketLike, targetUrl?: string, timeoutMs?: number }} CheckOptions */

/** @typedef {{ alive: boolean, remoteIp: string | null, latencyMs: number | null, error: string | null }} CheckOutcome */

const DEFAULT_TIMEOUT_MS = 8000;
const CRLF = '\r\n';

function targetOf(url) {
  const u = new URL(url);
  return { hostname: u.hostname, port: u.port ? Number(u.port) : 80 };
}

/** Read one chunk, or throw when the deadline passes first. */
function readChunk(reader, deadline) {
  const left = deadline - Date.now();
  if (left <= 0) return Promise.reject(new Error('timeout'));
  let timer;
  const timeout = new Promise((_, rej) => {
    timer = setTimeout(() => rej(new Error('timeout')), left);
  });
  return Promise.race([reader.read(), timeout]).finally(() => clearTimeout(timer));
}

/**
 * A buffered reader over the socket stream: a chunk that carries more than
 * the caller asked for must not lose the remainder - a proxy that pipelines
 * the handshake reply and the response into one write would otherwise look
 * like a dead proxy.
 */
function bufferedReader(reader) {
  let buf = new Uint8Array(0);
  const concat = (a, b) => {
    const out = new Uint8Array(a.length + b.length);
    out.set(a);
    out.set(b, a.length);
    return out;
  };
  return {
    async readN(n, deadline) {
      while (buf.length < n) {
        const { value, done } = await readChunk(reader, deadline);
        if (done) throw new Error('connection closed');
        buf = concat(buf, value);
      }
      const out = buf.subarray(0, n);
      buf = buf.subarray(n);
      return out;
    },
    async readUntil(marker, deadline) {
      for (;;) {
        // http framing is ascii, so text offsets are byte offsets
        const text = new TextDecoder().decode(buf);
        const idx = text.indexOf(marker);
        if (idx >= 0) {
          const cut = idx + marker.length;
          const head = text.slice(0, cut);
          buf = buf.subarray(cut);
          return head;
        }
        const { value, done } = await readChunk(reader, deadline);
        if (done) throw new Error('connection closed');
        buf = concat(buf, value);
      }
    },
    async readRest(deadline) {
      const dec = new TextDecoder();
      // whatever the buffered reader already holds belongs to this response
      let out = dec.decode(buf);
      buf = new Uint8Array(0);
      for (;;) {
        const { value, done } = await readChunk(reader, deadline);
        if (done) break;
        out += dec.decode(value, { stream: true });
        if (out.length > 64 * 1024) break;
      }
      return out;
    },
  };
}

/** Open a tunnel to the echo target through the proxy. */
async function openTunnel(socket, reader, proxy, hostname, port, deadline) {
  const writer = socket.writable.getWriter();
  const enc = new TextEncoder();
  if (proxy.protocol === 'socks5') {
    // raw bytes, not a string: TextEncoder.encode() would stringify the array
    await writer.write(Uint8Array.from([0x05, 0x01, 0x00]));
    const greet = await reader.readN(2, deadline);
    if (greet[0] !== 0x05 || greet[1] !== 0x00) throw new Error('socks5 greeting rejected');
    const req = [0x05, 0x01, 0x00, 0x01, ...proxy.host.split('.').map(Number), (port >> 8) & 0xff, port & 0xff];
    await writer.write(Uint8Array.from(req));
    // VER REP RSV ATYP: four bytes, then the bound address and port
    const head = await reader.readN(4, deadline);
    if (head[1] !== 0x00) throw new Error(`socks5 connect refused (${head[1]})`);
    const atyp = head[3];
    const addrLen = atyp === 0x01 ? 4 : atyp === 0x03 ? (await reader.readN(1, deadline))[0] : atyp === 0x04 ? 16 : 0;
    await reader.readN(addrLen + 2, deadline);
  } else {
    const target = `${hostname}:${port}`;
    await writer.write(enc.encode(`CONNECT ${target} HTTP/1.1${CRLF}Host: ${target}${CRLF}${CRLF}`));
    const head = await reader.readUntil(CRLF + CRLF, deadline);
    const m = /^HTTP\/1\.[01] (\d{3})/.exec(head);
    if (!m) throw new Error('malformed CONNECT reply');
    if (m[1] !== '200') throw new Error(`CONNECT -> ${m[1]}`);
  }
  return writer;
}

/** Check one proxy through the given socket factory. */
export async function checkProxyOnDemand(opts) {
  const started = Date.now();
  const deadline = started + (opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const target = targetOf(opts.targetUrl ?? 'http://httpbingo.org/get');
  const socket = opts.connect({ hostname: target.hostname, port: target.port });
  const reader = bufferedReader(socket.readable.getReader());
  try {
    const writer = await openTunnel(socket, reader, opts.proxy, target.hostname, target.port, deadline);
    const enc = new TextEncoder();
    await writer.write(
      enc.encode(
        `GET /get HTTP/1.1${CRLF}Host: ${target.hostname}${CRLF}User-Agent: open-proxy-pool${CRLF}Connection: close${CRLF}${CRLF}`,
      ),
    );
    const head = await reader.readUntil(CRLF + CRLF, deadline);
    const m = /^HTTP\/1\.[01] (\d{3})/.exec(head);
    if (!m) throw new Error('malformed response');
    const status = Number(m[1]);
    if (status < 200 || status >= 400) throw new Error(`HTTP ${status}`);

    // small echo payload; read until the proxy closes the stream
    const body = await reader.readRest(deadline + 2000);
    const origin = /"origin"\s*:\s*"([^"]+)"/.exec(body)?.[1] ?? null;
    return { alive: true, remoteIp: origin, latencyMs: Date.now() - started, error: null };
  } catch (e) {
    return { alive: false, remoteIp: null, latencyMs: null, error: (e && e.message) || String(e) };
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* already locked elsewhere */
    }
    await socket.close().catch(() => {});
  }
}
