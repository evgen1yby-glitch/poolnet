const MAX_LINES = 240;
const lines: string[] = [];

function clean(value: unknown): string {
  return String(value ?? '')
    .replace(/https?:\/\/\S+/gi, '[url]')
    .replace(/\b[A-Za-z0-9_-]{32,}\b/g, '[redacted]')
    .replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[ip]')
    .slice(0, 700);
}

export function logEvent(level: 'info' | 'warn' | 'error', area: string, message: string, meta?: Record<string, unknown>): void {
  const suffix = meta ? ` ${clean(JSON.stringify(meta))}` : '';
  lines.push(`${new Date().toISOString()} ${level.toUpperCase()} ${area}: ${clean(message)}${suffix}`);
  if (lines.length > MAX_LINES) lines.splice(0, lines.length - MAX_LINES);
}

export function diagnosticLog(): string {
  return lines.join('\n').slice(-32_000);
}
