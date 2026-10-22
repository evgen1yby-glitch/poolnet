import net from 'node:net';

export class NetError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'NetError';
  }
}

/** A buffered socket reader with hard deadlines on every read. */
export class SocketReader {
  private buf = Buffer.alloc(0);
  private ended = false;
  private onData = (d: Buffer) => {
    this.buf = Buffer.concat([this.buf, d]);
    this.pump();
  };
  private onEnd = () => {
    this.ended = true;
    this.pump();
  };

  constructor(private sock: net.Socket) {
    sock.on('data', this.onData);
    sock.on('end', this.onEnd);
    sock.on('close', this.onEnd);
    sock.on('error', this.onEnd);
  }

  /**
   * Hand the socket back to its next owner. Anything that already arrived -
   * a proxy may pipeline the CONNECT reply and the first response bytes in
   * one TCP segment - is returned so the next reader can prepend it. Without
   * this those bytes stay trapped in this reader's buffer and the request
   * that follows the handshake sees an empty response.
   */
  detach(): Buffer {
    this.sock.off('data', this.onData);
    this.sock.off('end', this.onEnd);
    this.sock.off('close', this.onEnd);
    this.sock.off('error', this.onEnd);
    const leftover = this.buf;
    this.buf = Buffer.alloc(0);
    return leftover;
  }

  private waiters: Array<() => void> = [];

  private pump() {
    const w = this.waiters;
    this.waiters = [];
    for (const f of w) f();
  }

  private size(): number {
    return this.buf.length;
  }

  private take(n: number): Buffer {
    const out = this.buf.subarray(0, n);
    this.buf = this.buf.subarray(n);
    return out;
  }

  async readN(n: number, timeoutMs: number): Promise<Buffer> {
    const deadline = Date.now() + timeoutMs;
    while (this.size() < n) {
      if (this.ended) throw new NetError('connection closed mid-read');
      const left = deadline - Date.now();
      if (left <= 0) throw new NetError('read timeout');
      await new Promise<void>((resolve) => {
        const t = setTimeout(resolve, Math.min(left, 50));
        this.waiters.push(() => {
          clearTimeout(t);
          resolve();
        });
      });
    }
    return this.take(n);
  }

  async readUntil(marker: Buffer | string, timeoutMs: number): Promise<Buffer> {
    const m = typeof marker === 'string' ? Buffer.from(marker, 'latin1') : marker;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const idx = this.buf.indexOf(m);
      if (idx >= 0) return this.take(idx + m.length);
      if (this.ended) throw new NetError('connection closed before marker');
      const left = deadline - Date.now();
      if (left <= 0) throw new NetError('read timeout');
      await new Promise<void>((resolve) => {
        const t = setTimeout(resolve, Math.min(left, 50));
        this.waiters.push(() => {
          clearTimeout(t);
          resolve();
        });
      });
    }
  }

  buffered(): Buffer {
    return this.buf;
  }
}

/** Connect a raw TCP socket to host:port with a hard timeout. */
export function tcpConnect(host: string, port: number, timeoutMs: number): Promise<net.Socket> {
  return new Promise((resolve, reject) => {
    const sock = net.connect({ host, port });
    const t = setTimeout(() => {
      sock.destroy();
      reject(new NetError(`tcp connect timeout ${host}:${port}`));
    }, timeoutMs);
    sock.once('connect', () => {
      clearTimeout(t);
      sock.setTimeout(0);
      resolve(sock);
    });
    sock.once('error', (e) => {
      clearTimeout(t);
      sock.destroy();
      reject(new NetError(`tcp ${host}:${port}: ${e.message}`));
    });
  });
}

export function destroyQuietly(sock: net.Socket | null | undefined): void {
  if (!sock) return;
  try {
    sock.destroy();
  } catch {
    /* ignore */
  }
}
