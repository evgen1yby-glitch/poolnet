import { isUsableIPv4, isValidPort, normalizeIPv4, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * Parse one text line that may contain a proxy.
 *
 * Supported (scheme always wins over the declared protocol):
 *   1.2.3.4:8080
 *   http://1.2.3.4:8080
 *   socks5://user:pass@1.2.3.4:1080
 *   socks4a://1.2.3.4:1080   (mapped to socks4)
 *   https://1.2.3.4:443      (mapped to http, we probe CONNECT)
 *   user:pass@1.2.3.4:8080
 * Lines may also carry inline comments (# ...) or surrounding whitespace.
 *
 * This is the regression surface for the historic bug where lines with a
 * scheme were silently dropped, zeroing out whole sources.
 */
export function parseProxyLine(line: string, defaultProtocol: ProxyProtocol): Candidate | null {
  const t = line.trim();
  if (!t || t.startsWith('#')) return null;

  const full =
    /^\s*(socks5|socks4|socks4a|socks4|http|https):\/\/(?:(.+)@)?\s*(\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(\d{1,5})\s*(?:[#\-/,;]\s*[^\s]*)?(?:\s+.*)?$/i;
  const m = full.exec(t);
  if (m) {
    const protoRaw = m[1]!.toLowerCase();
    const protocol: ProxyProtocol =
      protoRaw === 'socks5' ? 'socks5' : protoRaw.startsWith('socks4') ? 'socks4' : 'http';
    const creds = m[2];
    let user: string | undefined;
    let pass: string | undefined;
    if (creds && creds.includes(':')) {
      const idx = creds.lastIndexOf(':');
      user = creds.slice(0, idx);
      pass = creds.slice(idx + 1);
    }
    return candidate(protocol, m[3]!, Number(m[4]), user, pass);
  }

  // Lines may carry annotations after the token (`ip:port CC-A-S +`), which
  // several maintained lists ship next to the entry itself. The tail is any
  // of the separator forms real lists use - a hash, dash, comma, semicolon,
  // slash or plain whitespace - so no row is dropped for its punctuation.
  const withCreds = /^\s*(?:(.+)@)?\s*(\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(\d{1,5})\s*(?:[#\-/,;]\s*[^\s]*)?(?:\s+.*)?$/;
  const m2 = withCreds.exec(t);
  if (m2) {
    const creds = m2[1];
    let user: string | undefined;
    let pass: string | undefined;
    if (creds && creds.includes(':')) {
      const idx = creds.lastIndexOf(':');
      user = creds.slice(0, idx);
      pass = creds.slice(idx + 1);
    }
    return candidate(defaultProtocol, m2[2]!, Number(m2[3]), user, pass);
  }

  return null;
}

function candidate(
  protocol: ProxyProtocol,
  host: string,
  port: number,
  user?: string,
  pass?: string,
): Candidate | null {
  // 010.1.1.1 and 10.1.1.1 are the same proxy: one host, one key, one subnet
  host = normalizeIPv4(host);
  if (!isUsableIPv4(host) || !isValidPort(port)) return null;
  const c: Candidate = { protocol, host, port, source: '' };
  if (user) c.user = user;
  if (pass) c.pass = pass;
  return c;
}
