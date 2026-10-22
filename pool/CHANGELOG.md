# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses semantic versioning.

## [0.1.0] — 2026-10-14

First public release: the pipeline, the data products and the website.

### Added

- Distributed verification (`src/distributed/` + `opp serve`): a real HTTP
  coordinator that hands out batches and validates results against the job
  it issued, plus the node side (`opp node`) that polls, checks and reports.
  The node survives coordinator hiccups (bounded requests, explained
  failures, exponential backoff). Tests cover batching, forged results,
  unknown job ids, queue draining, token auth and a full node-coordinator
  round trip against local mocks

### Added

- `GET /v1/check?proxy=host:port&proto=socks5` on the edge API: a live
  single-proxy check over `cloudflare:sockets` (verdict, exit IP, latency,
  never cached). The site's "Check a proxy" section now works - set
  `data-api` on `<body>` to point it at your Worker. Unit tests cover the
  handshake, coalesced replies, refusals, non-200s and silence

### Added

- `npm run og` regenerates the social preview: a real 1200x630 PNG drawn
  from scratch (bitmap wordmark, brand gradient, live-rate bars) because no
  social network renders the SVG that shipped there before
- `scripts/check-site-structure.mjs` now also fails on duplicate ids,
  unresolvable i18n keys in either dictionary, and bundles missing fields
  the app reads — it caught the broken `a11y.check` aria-label on its first
  run

### Fixed

- Cloudflare Worker edge API (`workers/api/`): `/v1/stats`, `/v1/sources`,
  `/v1/history`, `/v1/proxies`, `/v1/list/:proto`, `/v1/country/:cc` with
  CORS and per-endpoint cache tuning; 7 tests cover routing, CORS, cache
  headers and origin failures

### Fixed

- `opp roast`: a weekly digest written from the benchmark (biggest published-
  vs-measured gap, most honest source, rank movement, staleness), with tests
  and a weekly workflow that publishes it to `data/roast.md`

### Fixed

- roundproxies.com public JSON API (8 pages × 500 = 3,947 entries, measured
  12.6–16.8% live), discovered behind the "Download all" button
- String-port tolerance in the geonode JSON parser (roundproxies sends them
  as strings), tested for both shapes

### Fixed

- advanced.name/freeproxy source (5 pages, ~485 entries): base64
  attribute decoding for address/port, type and country claims
  (measured live rate 41–86% per page — second only to flashproxy)

### Fixed

- POST source support (`method: post` + urlencoded `body`), used for
  spys.one's 500-row type-filtered lists that only answer POST with the
  rows-per-page field
- flashproxy raised to its full 2,000 entries (was capped at 1,000)
- `spys-one-socks`, `spys-one-http`, `spys-one-anonymous` sources

### Fixed

- spys.one source via a `node:vm` sandbox that executes the page's own
  obfuscated scripts to recover the ports (no headless browser)
- `opp check <source-id|url>`: fetch ONE source, validate EVERY candidate,
  report candidates/alive/live-rate/anonymity/latency/staleness/top errors —
  the honest answer to "is this list worth anything?"
- A captured spys.one fixture guards the deobfuscation with tests

### Fixed

- Source freshness dating via the GitHub API (`lastCommitDays` in
  `data/fetch-report.json`): files untouched for >90 days are flagged, so an
  abandoned source can never pass as live
- `bot/index.mjs` — a dependency-free Telegram bot serving `/get`, `/top` and
  `/stats` from the published JSON
- `docs/launch-kit.md` — the launch plan with concrete titles, timings and
  the Telegram growth path

### Fixed

**Pipeline**

- Source registry (`sources.yaml`) with 173 entries across plain text,
  geonode-style JSON APIs and HTML directories; per-source stats and
  yield warnings in `data/fetch-report.json`
- Tolerant parsing: bare `ip:port`, `scheme://`, credentials and annotation
  tails; geonode string ports; HTML cell fallback
- Even-stride sampling so every source is represented in each cycle
- Two-phase verification: TCP/handshake liveness (SOCKS4, SOCKS5, HTTP
  CONNECT plus absolute-form fallback for CDN-fronted proxies) and
  anonymity grading through header-echo targets
- Rotating liveness targets so one rate-limited echo endpoint cannot sink
  a cycle; 256 KB body cap; hard deadlines on every await
- Enrichment: exit IP, latency percentiles, rolling uptime windows
  (1 h / 24 h / 7 d / 30 d), ASN + org, country from an offline database
  (auto-downloaded DB-IP lite), TLS-MITM detection
- Store with a zero-dependency gzipped snapshot (Actions cache) or
  Postgres; re-check queue, dead-after retention, /24 diversity cap
- CLI: `fetch`, `validate`, `merge`, `publish`, `cycle`, `discover`
- Weekly source-discovery sweep over the GitHub API, filed as a review issue

**Data products**

- `data/all.txt`, `{http,socks4,socks5}.txt`, `top100.txt`, `top1000.txt`
- `data/proxies.json` with full metadata
- `data/country/<CC>.txt` shards for every country with ≥ 5 entries
- `data/stats.json`, `data/meta.json`, `data/history.json`
- shields.io endpoint payloads for README badges

**Website** (`site/`, static, no framework, no build)

- Search, protocol/grade/country filters, sorting, pagination
- Per-proxy drawer with uptime gauges, exit IP, network and copy actions
- Latency histogram, anonymity distribution, pool-size sparkline
- Proxy playground (checks any address through a free public checker)
- Shareable views via URL hash; export of the current view; compact mode
- Dark mode, skeletons, EN/RU localization, mobile card layout

**Repository**

- CI: ESLint, typecheck, 103 unit tests, YAML and asset guards, one live
  end-to-end cycle per push
- Refresh workflow on a 15-minute schedule with an 8-shard matrix
- Docs: architecture, sources, operations, examples; issue templates;
  CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, NOTICE

### Added

- roundproxies.com public JSON API (8 pages × 500 = 3,947 entries, measured
  12.6–16.8% live), discovered behind the "Download all" button
- String-port tolerance in the geonode JSON parser (roundproxies sends them
  as strings), tested for both shapes

### Fixed

- advanced.name/freeproxy source (5 pages, ~485 entries): base64
  attribute decoding for address/port, type and country claims
  (measured live rate 41–86% per page — second only to flashproxy)

### Fixed

- POST source support (`method: post` + urlencoded `body`), used for
  spys.one's 500-row type-filtered lists that only answer POST with the
  rows-per-page field
- flashproxy raised to its full 2,000 entries (was capped at 1,000)
- `spys-one-socks`, `spys-one-http`, `spys-one-anonymous` sources

### Fixed

- spys.one source via a `node:vm` sandbox that executes the page's own
  obfuscated scripts to recover the ports (no headless browser)
- `opp check <source-id|url>`: fetch ONE source, validate EVERY candidate,
  report candidates/alive/live-rate/anonymity/latency/staleness/top errors —
  the honest answer to "is this list worth anything?"
- A captured spys.one fixture guards the deobfuscation with tests

### Fixed

- Source freshness dating via the GitHub API (`lastCommitDays` in
  `data/fetch-report.json`): files untouched for >90 days are flagged, so an
  abandoned source can never pass as live
- `bot/index.mjs` — a dependency-free Telegram bot serving `/get`, `/top` and
  `/stats` from the published JSON
- `docs/launch-kit.md` — the launch plan with concrete titles, timings and
  the Telegram growth path

### Fixed

- `getfreeproxy.com` API sources (`gfp-http`, `gfp-https`, `gfp-socks4`,
  `gfp-socks5`) with a `bearer:` auth template expanded from `GFP_API_KEY`;
  without the variable the sources are skipped quietly, so public CI runs
  unchanged. `vmess`/`vless` entries the API also returns are dropped at
  parse time — real proxies, unsupported protocols.
- Per-source fair-share sampling: every enabled source is represented in
  every cycle (a 33-entry source in a 732k universe would otherwise never
  be sampled), with the cap always respected.
- Unit tests for the new parser, the auth/env source loader and the sampler.

### Fixed

- Sampling bias that starved the tail of the source registry
- `translate3d` called with two arguments (invalid CSS: the rail did not move)
- Hero grid interleaving on desktop
- Table columns clipped instead of scrolled on narrow viewports
- Placeholder substitution collisions (`TO` inside `TOTAL`)
- Socket push-back data loss during partial reads
- Unbounded response bodies (memory blow-up on hostile proxies)

[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
