import { parseProxyLine } from './plain.js';
import { parseJsonSource } from './json.js';
import { parseHtmlSource } from './html.js';
import { parseGfp } from './gfp.js';
import { parseSpys } from './spys.js';
import { parseAdvancedName } from './advancedname.js';
import { parseRoundproxies } from './roundproxies.js';
import type { Candidate } from '../sources/types.js';
import type { SourceSpec } from '../sources/types.js';

/** Parse a fetched source into candidates. Unknown lines are skipped. */
export function parseSource(res: { spec: SourceSpec; body: string }): Candidate[] {
  const out: Candidate[] = [];
  const defaultProtocol = res.spec.protocol ?? 'http';
  if (res.spec.format === 'spys') {
    for (const c of parseSpys(res.body, defaultProtocol)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  if (res.spec.format === 'advname') {
    for (const c of parseAdvancedName(res.body, defaultProtocol)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  if (res.spec.format === 'roundproxies') {
    for (const c of parseRoundproxies(res.body, defaultProtocol)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  if (res.spec.format === 'gfp') {
    for (const c of parseGfp(res.body)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  if (res.spec.format === 'json') {
    for (const c of parseJsonSource(res.body, defaultProtocol)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  if (res.spec.format === 'html') {
    for (const c of parseHtmlSource(res.body, defaultProtocol)) {
      c.source = res.spec.id;
      out.push(c);
    }
    return out;
  }
  for (const line of res.body.split(/\r?\n/)) {
    const c = parseProxyLine(line, defaultProtocol);
    if (c) {
      c.source = res.spec.id;
      out.push(c);
    }
  }
  return out;
}
