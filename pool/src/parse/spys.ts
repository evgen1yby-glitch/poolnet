import vm from 'node:vm';
import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

/**
 * spys.one publishes its proxy table with ports written by an obfuscated
 * script: the page packs its variable dictionary (Dean Edwards packer) and
 * then emits ports as `document.write(":"+(Name^Other)+(Name2^Other2))`.
 * Running the page's own scripts in a sandbox recovers the values without a
 * headless browser; every row's port is then computed from the expression
 * that sits inside that very row, so page furniture that also calls
 * document.write cannot shift the pairing.
 *
 * Metadata the page publishes per entry (type, anonymity, uptime) rides along
 * as the source's own claim — our checker still grades everything itself.
 */

// rows alternate between the spy1x and spy1xx classes; the port arrives as a
// document.write expression inside the row itself
const IP_ROW_RE = /<font class=spy14>(\d{1,3}(?:\.\d{1,3}){3})<script[^>]*>document\.write\(([\s\S]*?)\)<\/script>/g;
// the type is either bare text (type-filtered lists) or wrapped in a link
// whose URL names the type - the mixed list uses "<font>HTTP</font><font>S</font>"
const TYPE_RE = /<td colspan=1>(?:<font class=spy1>)?(HTTP|HTTPS|SOCKS4|SOCKS5|SOCKS)(?:<\/font>)?<\/td>/;
const TYPE_LINK_RE = /<a href='\/en\/([a-z0-9-]+?)-?proxy(?:-list)?\//;
const ANON_RE = /<font class=spy[15]>(NOA|ANM|HIA)<\/font>/;

const PROTOCOL_BY_TYPE: Record<string, ProxyProtocol | null> = {
  HTTP: 'http',
  HTTPS: 'http',
  SOCKS4: 'socks4',
  SOCKS5: 'socks5',
  SOCKS: null,
};

/** the type link of the mixed list names the type in its URL, not its text */
const TYPE_BY_LINK: Record<string, string> = {
  http: 'HTTP',
  'https-ssl': 'HTTPS',
  socks4: 'SOCKS4',
  socks5: 'SOCKS5',
  socks: 'SOCKS',
};

function makeSandbox(writes: string[]) {
  const element = () => ({
    style: {} as Record<string, string>,
    setAttribute() {},
    appendChild() {},
    removeChild() {},
    getElementsByTagName: () => [],
  });
  const sandbox: Record<string, unknown> = {
    document: {
      write: (s: unknown) => {
        writes.push(String(s));
        return s;
      },
      writeln: (s: unknown) => {
        writes.push(String(s));
        return s;
      },
      getElementById: () => null,
      getElementsByTagName: () => [],
      createElement: element,
      createTextNode: element,
      body: { appendChild() {}, removeChild() {} },
      onreadystatechange: null,
    },
    navigator: { userAgent: 'Mozilla/5.0' },
    location: { href: 'https://spys.one/en/free-proxy-list/', hostname: 'spys.one', protocol: 'https:', search: '' },
    screen: {},
    top: null,
    parent: null,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  return sandbox;
}

/**
 * Run every script of the page in one shared context so the packed variable
 * dictionary exists; the writes themselves are not used for pairing.
 * Returns the context, ready to evaluate a single row's expression.
 */
function pageContext(html: string): vm.Context {
  const writes: string[] = [];
  const sandbox = makeSandbox(writes);
  const ctx = vm.createContext(sandbox);
  // run every inline script in document order: the page defines a dictionary
  // of `name=number` assignments, then every port expression references it.
  // Analytics and DOM helpers crash harmlessly in the stub and are skipped.
  const scriptRe = /<script[^>]*>([\s\S]*?)<\/script>/g;
  for (const m of html.matchAll(scriptRe)) {
    const code = m[1];
    if (!code) continue;
    const isDictionary = /^[\s\w.;=^]+$/.test(code) && /\w+=\d+;/.test(code);
    const isWrite = code.includes('document.write');
    const isPacker = code.includes('eval(function');
    if (!isDictionary && !isWrite && !isPacker) continue;
    try {
      // a source's script is untrusted: bound it, a hang would freeze the job
      vm.runInContext(code, ctx, { timeout: 200 });
    } catch {
      /* DOM-dependent fragments are irrelevant to the port values */
    }
  }
  return ctx;
}

/** Writes come wrapped in font tags; the port is what is left after stripping. */
const portOf = (fragment: string): number | null => {
  const stripped = fragment.replace(/<[^>]*>/g, '');
  const m = /^:(\d{2,5})$/.exec(stripped);
  return m ? Number(m[1]) : null;
};

export interface SpysEntry extends Candidate {
  /** what the page itself claims; our checker still grades independently */
  claim: { type: string | null; anonymity: string | null; uptime: string | null };
}

export function parseSpys(html: string, _defaultProtocol: ProxyProtocol): SpysEntry[] {
  const ctx = pageContext(html);
  const out: SpysEntry[] = [];
  for (const m of html.matchAll(IP_ROW_RE)) {
    const host = m[1]!;
    if (!html.includes('document.write')) break;
    // the port is computed from the expression inside THIS row: page
    // furniture that also calls document.write cannot shift the pairing
    let port: number | null = null;
    try {
      const value = vm.runInContext(m[2]!, ctx, { timeout: 200 });
      port = typeof value === 'number' ? value : portOf(String(value));
    } catch {
      port = null;
    }
    if (port === null || !isUsableIPv4(host) || !isValidPort(port)) continue;

    // the row continues after the </script> — read a slice for the claims
    const rowSlice = html.slice(m.index, m.index + 900);
    const type =
      TYPE_RE.exec(rowSlice)?.[1] ?? TYPE_BY_LINK[TYPE_LINK_RE.exec(rowSlice)?.[1]!.toLowerCase() ?? ''] ?? null;
    const anonymity = ANON_RE.exec(rowSlice)?.[1] ?? null;
    const uptime = /<acronym title='[^']*?last check status=(\w+)/.exec(rowSlice)?.[1] ?? null;

    const protocol = (type && PROTOCOL_BY_TYPE[type]) || 'http';
    const entry: SpysEntry = {
      protocol,
      host,
      port,
      source: '',
      claim: { type, anonymity, uptime },
    };
    out.push(entry);
  }
  return out;
}
