import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

/** Gzipped JSONL: one record per line, stream-friendly for 50k+ rows. */
export function readJsonlGz<T>(file: string): T[] {
  if (!fs.existsSync(file)) return [];
  const text = zlib.gunzipSync(fs.readFileSync(file)).toString('utf8');
  const out: T[] = [];
  let malformed = 0;
  for (const line of text.split('\n')) {
    if (!line) continue;
    try {
      out.push(JSON.parse(line) as T);
    } catch {
      malformed++;
    }
  }
  // a partially corrupt shard must not look like a clean, smaller shard
  if (malformed > 0) {
    throw new Error(`${file}: ${malformed} malformed line(s) of ${out.length + malformed}`);
  }
  return out;
}

export interface JsonlGzWriter<T> {
  write(row: T): void;
  close(): Promise<string>;
}

export function jsonlGzWriter<T>(file: string): JsonlGzWriter<T> {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  const ws = zlib.createGzip();
  const out = fs.createWriteStream(tmp);
  ws.pipe(out);
  const backpressure: Array<Promise<void>> = [];

  const write = (row: T) => {
    if (!ws.write(JSON.stringify(row) + '\n')) {
      backpressure.push(new Promise<void>((res) => ws.once('drain', () => res())));
    }
  };

  const close = () =>
    new Promise<string>((resolve, reject) => {
      ws.end(() => {
        out.on('close', () => {
          try {
            fs.renameSync(tmp, file);
            resolve(file);
          } catch (e) {
            reject(e);
          }
        });
      });
      void Promise.all(backpressure);
    });

  return { write, close };
}

export function atomicWriteJson(file: string, data: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n');
  fs.renameSync(tmp, file);
}
