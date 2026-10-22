#!/usr/bin/env node
/**
 * open-proxy-pool Telegram bot — the pool, in a chat.
 *
 * Zero dependencies (long-polling over fetch), single file. It reads the same
 * published JSON the website uses, so it never talks to a proxy itself.
 *
 * Usage:
 *   BOT_TOKEN=123:abc OP_POOL_URL=https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data node bot/index.mjs
 *
 * Commands:
 *   /get [protocol] [country]   one working proxy, e.g. /get socks5 US
 *   /top [n]                    the n best right now (default 10)
 *   /stats                      pool size, protocols, countries, median latency
 *   /help                       this text
 *
 * Get a token from @BotFather, run it anywhere with outbound HTTPS. The
 * repository's README links to the deployed instance.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// ---------------------------------------------------------------- data
async function loadJson(name) {
  const url = process.env.OP_POOL_URL
    ? `${process.env.OP_POOL_URL.replace(/\/$/, '')}/${name}`
    : path.join(ROOT, 'data', name);
  if (url.startsWith('http')) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
    return res.json();
  }
  return JSON.parse(await readFile(url, 'utf8'));
}

/** /get filters: socks5|socks4|http and an optional 2-letter country. */
export function pickFrom(pool, { protocol, country }) {
  const filtered = pool.filter((p) => (!protocol || p.protocol === protocol) && (!country || p.country === country));
  if (!filtered.length) return null;
  // the file is published best-first; sample the head so quality stays high
  const head = filtered.slice(0, Math.min(200, filtered.length));
  return head[Math.floor(Math.random() * head.length)];
}

export function formatProxy(p) {
  const scheme = p.protocol === 'socks5' ? 'socks5' : p.protocol;
  const geo = [p.city, p.country].filter(Boolean).join(', ');
  const parts = [
    `<code>${scheme}://${p.host}:${p.port}</code>`,
    `grade <b>${p.grade}</b> · ${p.latency === null || p.latency === undefined ? 'latency n/a' : `${p.latency} ms`}`,
    geo ? `📍 ${geo}` : null,
    p.uptime7d !== null && p.uptime7d !== undefined ? `uptime 7d ${p.uptime7d}%` : null,
    p.mitm ? '⚠️ terminates TLS — treat as hostile' : null,
  ];
  return parts.filter(Boolean).join('\n');
}

export function formatStats(meta) {
  const byProto = Object.entries(meta.byProtocol)
    .map(([k, v]) => `${k} ${v}`)
    .join(' · ');
  return [
    `<b>${meta.total.toLocaleString('en-US')}</b> proxies alive right now`,
    `${byProto}`,
    `${meta.countries.length} countries · median ${meta.medianLatencyMs ?? '—'} ms · p95 ${meta.p95LatencyMs ?? '—'} ms`,
    `sources ${meta.sourcesOk}/${meta.sourcesTotal}`,
    `measured ${meta.generatedIso.replace('T', ' ').slice(0, 16)} UTC`,
  ].join('\n');
}

// ---------------------------------------------------------------- telegram
const API = (token, method, body) =>
  fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json());

const HELP = [
  '<b>Proxy pool bot</b> — every proxy answered a full request through a real connection.',
  '',
  '<b>/get [protocol] [country]</b> — one working proxy',
  '  e.g. <code>/get socks5 US</code>, <code>/get http</code>',
  '<b>/top [n]</b> — best n right now (default 10)',
  '<b>/stats</b> — pool size, protocols, countries',
  '',
  'These are public proxies run by strangers: never send credentials, personal data or payments through them.',
].join('\n');

export function parseCommand(text) {
  const [cmd, ...args] = text.trim().split(/\s+/);
  const name = (cmd || '').replace(/^\/(\w+)(@\w+)?/, '$1').toLowerCase();
  const protocol = ['socks5', 'socks4', 'http'].includes((args[0] || '').toLowerCase())
    ? (args[0] || '').toLowerCase()
    : null;
  const countryToken = (protocol ? args[1] : args[0]) || null;
  const country = countryToken && /^[A-Za-z]{2}$/.test(countryToken) ? countryToken.toUpperCase() : null;
  const size = args.map((a) => Number(a)).find((n) => Number.isFinite(n) && n > 0);
  return { name, protocol, country, size: size ?? null };
}

/**
 * Resolves parsed filters against the pool's real country list. A 2-letter
 * token that is not a known country is a typo, not a filter — the caller
 * explains it instead of silently answering "nothing in XX".
 */
export function resolveFilters(parsed, knownCountries) {
  const known = new Set(knownCountries);
  const country = parsed.country && known.has(parsed.country) ? parsed.country : null;
  return { protocol: parsed.protocol, country, typo: parsed.country && !country ? parsed.country : null };
}

async function handleUpdate(update, ctx) {
  const msg = update.message;
  if (!msg || !msg.text) return;
  const chatId = msg.chat.id;
  const parsed = parseCommand(msg.text);
  const { name } = parsed;
  const filters = resolveFilters(
    parsed,
    ctx.meta.countries.map((c) => c.cc),
  );
  const { protocol, country, typo } = filters;
  const n = parsed.size;
  try {
    if (name === 'get') {
      const meta = ctx.meta;
      if (typo) {
        const sample = ctx.meta.countries
          .slice(0, 12)
          .map((c) => c.cc)
          .join(' ');
        await ctx.send(chatId, `Unknown country ${typo}. Try one of: ${sample} …`);
        return;
      }
      const p = pickFrom(ctx.pool, { protocol, country });
      if (!p) {
        await ctx.send(
          chatId,
          `No alive ${protocol ?? 'proxy'}${country ? ` in ${country}` : ''} right now. Try /stats.`,
        );
        return;
      }
      await ctx.send(chatId, formatProxy(p) + `\n\npool size ${meta.total.toLocaleString('en-US')} · /help`);
    } else if (name === 'top') {
      const list = ctx.pool.slice(0, Math.min(Math.max(n || 10, 1), 50));
      const lines = list.map(
        (p, i) => `${i + 1}. <code>${p.protocol}://${p.host}:${p.port}</code> ${p.country ?? ''} ${p.latency ?? '?'}ms`,
      );
      await ctx.send(chatId, `<b>Best ${list.length} right now</b>\n${lines.join('\n')}`);
    } else if (name === 'stats') {
      await ctx.send(chatId, formatStats(ctx.meta));
    } else {
      await ctx.send(chatId, HELP);
    }
  } catch (e) {
    await ctx.send(chatId, `Pool data failed to load: ${e.message}`);
  }
}

async function main() {
  const token = process.env.BOT_TOKEN;
  if (!token) {
    console.error('set BOT_TOKEN (from @BotFather)');
    process.exit(1);
  }
  const [meta, pool] = await Promise.all([loadJson('meta.json'), loadJson('proxies.json')]);
  const ctx = {
    meta,
    pool,
    send: (chatId, text) =>
      API(token, 'sendMessage', { chat_id: chatId, text, parse_mode: 'HTML', disable_web_page_preview: true }).then(
        () => {},
      ),
  };
  console.log(`bot ready — pool ${pool.length} proxies, sources ${meta.sourcesOk}/${meta.sourcesTotal}`);

  let offset = 0;
  for (;;) {
    try {
      const updates = await API(token, 'getUpdates', { offset, timeout: 30 });
      for (const u of updates.result || []) {
        offset = u.update_id + 1;
        await handleUpdate(u, ctx);
      }
    } catch (e) {
      console.error('poll failed:', e.message);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
