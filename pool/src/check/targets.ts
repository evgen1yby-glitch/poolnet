import { config } from '../config.js';
import type { EchoTarget } from './errors.js';

interface Template {
  match: RegExp;
  parser: EchoTarget['parser'];
  label: string;
}

const TEMPLATES: Template[] = [
  { match: /ipify\.org/i, parser: 'text', label: 'ipify' },
  { match: /ipinfo\.io/i, parser: 'text', label: 'ipinfo' },
  { match: /ifconfig\.me/i, parser: 'text', label: 'ifconfig' },
  { match: /icanhazip\.com/i, parser: 'text', label: 'icanhazip' },
  { match: /ident\.me/i, parser: 'text', label: 'ident' },
  { match: /httpbingo\.org/i, parser: 'json', label: 'httpbingo' },
  { match: /postman-echo\.com/i, parser: 'json', label: 'postman-echo' },
  { match: /httpbin\.org/i, parser: 'json', label: 'httpbin' },
  { match: /(^|\.)1\.1\.1\.1$|cloudflare-dns\.com/i, parser: 'none', label: 'cloudflare' },
];

export function targetFor(url: string): EchoTarget {
  for (const t of TEMPLATES) {
    if (t.match.test(url)) return { url, parser: t.parser, label: t.label };
  }
  const parser: EchoTarget['parser'] = /json|\/get\b|\/ip\b/i.test(url) ? 'json' : 'text';
  return { url, parser, label: new URL(url).host };
}

export function httpFallbackFor(t: EchoTarget): EchoTarget {
  if (!t.url.startsWith('https://')) return t;
  const u = new URL(t.url);
  return { url: `http://${u.host}${u.pathname}${u.search}`, parser: t.parser, label: t.label };
}

export function defaultTargets(): EchoTarget[] {
  return config().checkTargets.map(targetFor);
}
