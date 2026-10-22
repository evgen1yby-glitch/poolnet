#!/usr/bin/env node
/**
 * Generates the social preview image (site/assets/og.png).
 *
 * og:image must be a raster format — every major network ignores SVG, so the
 * file is drawn here from scratch: a 5x7 bitmap wordmark over the brand
 * gradient plus a bar-chart silhouette, written as a real PNG with zlib. No
 * image library, no build step, deterministic output.
 *
 * Usage: node scripts/make-og.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const W = 1200;
const H = 630;

const FONT = {
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  B: ['11110', '10001', '10001', '11110', '10001', '10001', '11110'],
  C: ['01110', '10001', '10000', '10000', '10000', '10001', '01110'],
  D: ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  F: ['11111', '10000', '10000', '11110', '10000', '10000', '10000'],
  G: ['01110', '10001', '10000', '10111', '10001', '10001', '01110'],
  H: ['10001', '10001', '10001', '11111', '10001', '10001', '10001'],
  I: ['11111', '00100', '00100', '00100', '00100', '00100', '11111'],
  J: ['00111', '00010', '00010', '00010', '00010', '10010', '01100'],
  K: ['10001', '10010', '10100', '11000', '10100', '10010', '10001'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  N: '10001|11001|11001|10101|10011|10011|10001',
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  P: ['11110', '10001', '10001', '11110', '10000', '10000', '10000'],
  Q: ['01110', '10001', '10001', '10001', '10101', '10010', '01101'],
  R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
  S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  U: ['10001', '10001', '10001', '10001', '10001', '10001', '01110'],
  V: ['10001', '10001', '10001', '10001', '10001', '01010', '00100'],
  W: ['10001', '10001', '10001', '10101', '10101', '11011', '10001'],
  X: ['10001', '10001', '01010', '00100', '01010', '10001', '10001'],
  Y: ['10001', '10001', '01010', '00100', '00100', '00100', '00100'],
  Z: ['11111', '00001', '00010', '00100', '01000', '10000', '11111'],
  0: ['01110', '10001', '10011', '10101', '11001', '10001', '01110'],
  1: ['00100', '01100', '00100', '00100', '00100', '00100', '01110'],
  2: ['01110', '10001', '00001', '00110', '01000', '10000', '11111'],
  3: ['11111', '00010', '00100', '00010', '00001', '10001', '01110'],
  4: ['00010', '00110', '01010', '10010', '11111', '00010', '00010'],
  5: ['11111', '10000', '11110', '00001', '00001', '10001', '01110'],
  6: ['00110', '01000', '10000', '11110', '10001', '10001', '01110'],
  7: ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
  8: ['01110', '10001', '10001', '01110', '10001', '10001', '01110'],
  9: ['01110', '10001', '10001', '01111', '00001', '00010', '01100'],
  '.': ['00000', '00000', '00000', '00000', '00000', '01100', '01100'],
  ',': ['00000', '00000', '00000', '00000', '01100', '01100', '11000'],
  '-': ['00000', '00000', '00000', '11111', '00000', '00000', '00000'],
  ':': ['00000', '01100', '01100', '00000', '01100', '01100', '00000'],
  '/': ['00001', '00010', '00010', '00100', '01000', '01000', '10000'],
  ' ': ['00000', '00000', '00000', '00000', '00000', '00000', '00000'],
};
const norm = (c) => (typeof FONT[c] === 'string' ? FONT[c].split('|') : FONT[c]);

const img = Buffer.alloc(W * H * 4);
const set = (x, y, [r, g, b], a = 255) => {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const i = (y * W + x) * 4;
  img[i] = r;
  img[i + 1] = g;
  img[i + 2] = b;
  img[i + 3] = a;
};
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

const BG_TOP = [11, 16, 23];
const BG_BOTTOM = [17, 24, 39];
const INK = [231, 236, 244];
const MUTED = [185, 196, 214];
const GREEN = [10, 138, 95];
const INDIGO = [124, 123, 245];

for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const t = y / H;
    set(x, y, mix(BG_TOP, BG_BOTTOM, t));
  }
}

// a soft brand glow, top-left and bottom-right
for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const g1 = Math.max(0, 1 - Math.hypot(x - 120, y - 90) / 520);
    const g2 = Math.max(0, 1 - Math.hypot(x - (W - 90), y - (H - 70)) / 620);
    const glow = Math.min(0.22, g1 * 0.22 + g2 * 0.18);
    const base = [img[(y * W + x) * 4], img[(y * W + x) * 4 + 1], img[(y * W + x) * 4 + 2]];
    set(x, y, mix(base, INDIGO, glow * 0.6), 255);
  }
}

function text(str, x0, y0, scale, color) {
  let x = x0;
  for (const ch of str.toUpperCase()) {
    const glyph = norm(ch);
    if (!glyph) {
      x += 4 * scale;
      continue;
    }
    for (let r = 0; r < glyph.length; r++) {
      for (let c = 0; c < 5; c++) {
        if (glyph[r][c] === '1') {
          for (let sy = 0; sy < scale; sy++) {
            for (let sx = 0; sx < scale; sx++) set(x + c * scale + sx, y0 + r * scale + sy, color);
          }
        }
      }
    }
    x += 6 * scale;
  }
  return x;
}

// wordmark
text('OPEN PROXY POOL', 96, 118, 9, INK);
text('EVERY LIST, MEASURED BY ITS OWN PROXIES', 100, 200, 3, MUTED);

// bar-chart silhouette: the benchmark story in one glance
const bars = [0.18, 0.34, 0.22, 0.48, 0.4, 0.62, 0.55, 0.74, 0.68, 0.86, 0.9, 1];
const baseY = 520;
const barW = 56;
const gap = 20;
const startX = 96;
bars.forEach((v, i) => {
  const h = Math.round(240 * v);
  const x = startX + i * (barW + gap);
  const color = i >= bars.length - 3 ? GREEN : INDIGO;
  for (let y = baseY - h; y < baseY; y++) {
    for (let x2 = x; x2 < x + barW; x2++) {
      const t = (baseY - y) / 240;
      set(x2, y, mix(color, BG_TOP, Math.min(0.35, t * 0.35)));
    }
  }
});
// baseline
for (let x = startX - 8; x < startX + bars.length * (barW + gap); x++) {
  for (let y = baseY; y < baseY + 4; y++) set(x, y, [40, 52, 72]);
}
text('LIVE RATE BY SOURCE', 96, 556, 3, MUTED);
text('194 SOURCES', 830, 320, 4, INK);
text('CHECKED EVERY 15 MIN', 834, 380, 3, MUTED);

// ---- png encode ----
const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
};
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(W, 0);
ihdr.writeUInt32BE(H, 4);
ihdr[8] = 8; // bit depth
ihdr[9] = 6; // truecolour + alpha
const raw = Buffer.alloc(H * (1 + W * 4));
for (let y = 0; y < H; y++) {
  raw[y * (1 + W * 4)] = 0; // filter: none
  img.copy(raw, y * (1 + W * 4) + 1, y * W * 4, (y + 1) * W * 4);
}
const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk('IHDR', ihdr),
  chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
  chunk('IEND', Buffer.alloc(0)),
]);
const out = path.join(root, 'site', 'assets', 'og.png');
fs.writeFileSync(out, png);
console.log(`og: wrote ${out} (${(png.length / 1024).toFixed(1)} kB)`);
