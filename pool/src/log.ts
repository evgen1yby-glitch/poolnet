let DEBUG = false;

export function setDebug(v: boolean): void {
  DEBUG = v;
}

function ts(): string {
  return new Date().toISOString();
}

export const log = {
  info: (msg: string) => console.log(`${ts()} INFO  ${msg}`),
  warn: (msg: string) => console.warn(`${ts()} WARN  ${msg}`),
  error: (msg: string) => console.error(`${ts()} ERROR ${msg}`),
  debug: (msg: string) => {
    if (DEBUG) console.log(`${ts()} DEBUG ${msg}`);
  },
};
