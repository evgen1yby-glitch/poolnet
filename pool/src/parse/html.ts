/**
 * HTML sources (proxy directory sites): extract ip:port pairs from raw HTML.
 *
 * These sites embed the rows server-side, either as a text block or as
 * table cells (IP in one cell, port in the next), so a plain token scan
 * plus an adjacent-cell fallback covers both layouts without a DOM parser.
 */
import { isUsableIPv4, isValidPort, type Candidate, type ProxyProtocol } from '../sources/types.js';

const DIRECT = /\b(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})\b/g;
const CELLS = />\s*(\d{1,3}(?:\.\d{1,3}){3})\s*<[^>]*>\s*(?:<[^>]*>\s*)*(\d{2,5})\s*</g;

export function parseHtmlSource(text: string, defaultProtocol: ProxyProtocol): Candidate[] {
  const out: Candidate[] = [];
  const seen = new Set<string>();

  const push = (host: string, port: number) => {
    if (!isUsableIPv4(host) || !isValidPort(port)) return;
    const k = `${host}:${port}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push({ protocol: defaultProtocol, host, port, source: '' });
  };

  // Both shapes are parsed, then the richer one wins: a single ip:port inside
  // a <script> must not make a 300-row table parse as one candidate.
  const direct = [...text.matchAll(DIRECT)].map((m) => ({ host: m[1]!, port: Number(m[2]) }));
  const cells = [...text.matchAll(CELLS)].map((m) => ({ host: m[1]!, port: Number(m[2]) }));
  for (const c of direct.length >= cells.length ? direct : cells) push(c.host, c.port);
  return out;
}
