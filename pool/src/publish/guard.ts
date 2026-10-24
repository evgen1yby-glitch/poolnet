import fs from 'node:fs';
import path from 'node:path';

export interface PublicationGuard {
  open: boolean;
  previous: number;
  next: number;
}

/**
 * Refuse a publication that loses more than half of the last one.
 *
 * A checker bug, an expired TLS certificate, a blocked echo provider or a
 * provider-wide outage looks exactly like "almost every proxy died". Replacing
 * the last known-good files in that state turns a temporary failure into a
 * public outage. Keep the previous files and record the refusal instead.
 */
export function publicationGuard(dataDir: string, next: number): PublicationGuard {
  let previous = 0;
  try {
    const meta = JSON.parse(fs.readFileSync(path.join(dataDir, 'meta.json'), 'utf8')) as {
      counts?: { published?: unknown };
    };
    previous = Number(meta?.counts?.published) || 0;
  } catch {
    // First publication: nothing to protect.
    return { open: false, previous: 0, next };
  }
  const open = previous >= 500 && next < previous * 0.5;
  return { open, previous, next };
}
