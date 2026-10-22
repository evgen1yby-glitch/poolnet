# Edge API (Cloudflare Worker)

A stateless Worker that serves the published data with CORS and edge caching.
The repository stays the source of truth: the Worker reads the same files the
website uses (from GitHub raw or jsDelivr) and only adds what a public API
needs.

## Deploy

```bash
cd workers/api
npm i -g wrangler
wrangler login
wrangler deploy          # wrangler.toml in this directory points at index.js
```

Then set `ORIGIN` (no trailing slash) — a runtime secret, never compiled in:

```bash
wrangler secret put ORIGIN
# e.g. https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data
```

## Endpoints

| Route                 | Serves                                                | Cache                     |
| --------------------- | ----------------------------------------------------- | ------------------------- |
| `GET /v1/stats`       | pool statistics                                       | 60 s browser / 5 min edge |
| `GET /v1/sources`     | the benchmark of public lists                         | 60 s / 5 min              |
| `GET /v1/proxies`     | full metadata for every proxy                         | 60 s / 5 min              |
| `GET /v1/benchmark`   | same payload as `/v1/sources`                         | 60 s / 5 min              |
| `GET /v1/history`     | pool sizes and composition over time (`history.json`) | 5 min / 1 h               |
| `GET /v1/list/:proto` | `all`, `http`, `socks4`, `socks5`                     | 60 s / 5 min              |
| `GET /v1/country/:cc` | country shard                                         | 5 min / 1 h               |
| `GET /`               | the endpoint index                                    | 1 h / 24 h                |

```bash
curl https://<worker>.workers.dev/v1/stats
curl https://<worker>.workers.dev/v1/list/socks5 | head
curl https://<worker>.workers.dev/v1/country/US
curl "https://<worker>.workers.dev/v1/check?proxy=45.84.13.153:1080&proto=socks5"
```

The site's "Check a proxy" box calls `/v1/check`; point it at this Worker by
setting `data-api="https://<worker>.workers.dev"` on the page's `<body>`.

## Local development

```bash
cd workers/api
wrangler dev             # reads ORIGIN from .dev.vars or from `wrangler secret put`
```

`ORIGIN` is read at request time, so it can never drift from what the
repository actually publishes. Methods other than GET/OPTIONS get a 405.

The Worker holds no state, so it can be redeployed by anyone with Cloudflare
access; the only value it needs is `ORIGIN`.
