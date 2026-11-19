# Source registry

`sources.yaml` is the single source of truth for where raw proxies come from.
The fetch job is the only consumer; nothing else hard-codes URLs.

## Entry format

```yaml
- id: my-source-socks5 # stable id used in stats and the disable log
  url: https://example.com/list.txt
  format: plain # plain | json (geonode style)
  protocol: socks5 # default when a line carries no scheme
  enabled: true # optional, default true
```

## What "plain" accepts

One proxy per line, optionally with an inline comment:

```
1.2.3.4:8080
http://1.2.3.4:3128
socks5://user:pass@5.6.7.8:1080
https://1.2.3.4:443          # counted as http, probed with CONNECT
socks4a://1.2.3.4:1080       # counted as socks4
208.102.51.6:58208:United States  # trailing colon label (hideip.me style)
```

The scheme in the line always wins over the entry's `protocol`.
`0.0.0.0`, `127.0.0.1` and invalid ports are rejected. IPv6 and hostnames are
not supported by the checkers and are skipped.

## What "json" accepts

A JSON payload whose entries are proxies. `src/parse/json.ts` auto-detects
four shapes published by the APIs we consume:

```json
{ "data": [ { "ip": "1.2.3.4", "port": 1080, "protocols": ["socks5"] } ] }
```

- **geonode / roundproxies** — `{data:[{ip, port, protocols:[…]}]}` (the
  original shape; string ports accepted).
- **charlespikachu** — `{data:[{ip, port, protocol:"Socks5"}]}` (singular
  `protocol` string; case-insensitive, and combined values such as
  `"Http, Socks5"` are split).
- **mauricegift** — `{proxies:["ip:port", …]}` (plain string array).
- **proxytee** — `{proxies:[{host, port, proxy_type, types:[{type}]}]}`.

The protocol is the first supported one in the project's precedence
(`socks5` > `http` > `socks4`); when a row declares none, the entry's
`protocol` is used. `https` folds to `http`. Rows without a usable public
IPv4 or a valid port are dropped. A top-level object with a `data` or
`proxies` array is required; anything else yields an empty set.

## Health rules

- A source that 200s but yields zero proxies is a warning, not a silent
  pass — `data/fetch-report.json` records per-source yield.
- A source that fails (DNS, timeout, 4xx/5xx) is skipped for that cycle and
  reported; persistent failures should be flipped to `enabled: false`
  instead of deleted, so history stays readable.
- Sources are fetched at most once per cycle, with redirects capped at 3
  hops and a contact-bearing User-Agent.

The weekly `discover.yml` sweep proposes new candidates for review
(measured yield >= 50); merging them is a normal PR.

## Opaque sources

One directory obfuscates its table on purpose: **spys.one** writes ports via
`document.write(":"+(name^other)+...)` with a dictionary of `name=number`
assignments. The `spys` parser runs every inline script of the page in a
`node:vm` sandbox with a capturing `document` and pairs each address with the
port fragment in document order — no headless browser, no proxy of the page's
own logic. The source's claims (type, anonymity, uptime) ride along as
metadata; our checker still grades everything independently.

The sandbox only receives stubs (`document.write`, `location`, `navigator`);
page scripts that need the real DOM crash silently and their output is
irrelevant to the ports.

**Two shapes, one parser.** The mixed free list serves its 30 most recent
entries over GET. The type-filtered lists (`/en/socks-proxy-list/`,
`/en/http-proxy-list/`, `/en/anonymous-proxy-list/`) serve **500 rows per
request, but only through POST** with the rows-per-page form field:

```yaml
- id: spys-one-socks
  url: https://spys.one/en/socks-proxy-list/
  format: spys
  method: post
  body: xpp=5 # 0=30, 1=50, 2=100, 3=200, 4=300, 5=500
```

Note for maintainers: the site rate-limits the full page — the first request
in a while returns 500 rows, immediate follow-ups fall back to the 30-row
teaser. The parser handles both shapes and the fetch report records the
count per cycle, so the degradation is visible instead of silent.

## Obfuscated and encoded pages

Two directories publish proxies in encoded form, both handled in-repo:

**spys.one** — ports written by a packed script; the parser runs the page's
own scripts in a `node:vm` sandbox (see above).

**advanced.name/freeproxy** — address and port are base64 attribute values
(`<td data-ip="NDcuODUuMTMuMTk4">`), type is an anchor, country is a flag
class. 100 rows per page over five pages (~485 entries), decoded in
`src/parse/advancedname.ts`. Measured live rate per page: 41–86%.

**roundproxies.com/free-proxy-list** — the page's "Download all 8,384 proxies
online" button calls `GET /api/get-free-proxies/?limit=500&page=N`: 500 entries
per page with the source's own anonymity/latency/uptime/geo claims, eight pages
for 3,947. Registered as `roundproxies-api-1..8` (format `json`; string ports
are accepted). Measured live rate 12.6–16.8% per page. The earlier HTML-table
source is superseded by the API; the parser stays for the table shape.

Ruled out (checked, not integrated): **free-proxy.cz** (main page responds,
but every `/ru/proxylist/main/<n>` page that actually holds the 3,291 entries
fails to connect — requests are dropped), **proxycompass.com/free-proxy** and
**free.geonix.com** render their tables client-side behind JS bundles with no
open endpoint (`free.geonix.com/api/front/main/proxy/list` answers 405 to GET
and 500 to the documented POST shape). Both would need a headless browser,
which the pipeline deliberately avoids.

## Sources that need a key

Some providers publish an API instead of a file. Their registry entry carries
an `auth` template referencing an environment variable, and the loader
expands `${VAR}` at startup:

```yaml
- id: gfp-socks5
  url: https://api.getfreeproxy.com/v1/proxies?protocol=socks5
  format: gfp
  auth: bearer:${GFP_API_KEY}
```

Rules that keep this safe:

- **The key never lives in the repository.** `sources.yaml` holds only the
  `${VAR}` reference; the value comes from the environment (repository
  secret `GFP_API_KEY` in Actions, local `.env` / shell otherwise).
- **A missing key skips the source quietly** — the cycle logs
  `skipped — auth env unset` and runs on the remaining sources, so a public
  repo without the secret keeps working.
- **`format: gfp`** understands getfreeproxy.com records and keeps only the
  protocols this pipeline can verify (`http`, `https`→http, `socks4`,
  `socks5`). The API also returns `vmess`/`vless` entries; they are real
  proxies but unsupported protocols, so they are dropped at parse time.
  Credentials (`user`/`passwd`) travel with the candidate when present.

Getting a key: <https://getfreeproxy.com> (free tier, 10 proxies per
request; filtered by `protocol`).

## Discover sweep 2026-11-19: +37 SOCKS5 + 3 JSON sources

A deep audit on 2026-11-19 ran two parallel research subagents plus manual
curl verification against every candidate. The result: **37 new `plain`
SOCKS5 sources** appended to `sources.yaml`, all returning `ip:port` or
`socks5://ip:port` on stable `raw.githubusercontent.com` / jsdelivr URLs,
plus **3 JSON sources** enabled after extending `src/parse/json.ts` (see
above). Owners are disjoint from the pre-existing registry. Total raw
candidates added: ~70 000 lines per cycle (pre-deduplication), with the
largest single sources being `noctiro-getproxy` (16 378),
`meid1981101-socks5-3` (9 991), `anonym0uswork1221` (5 976),
`runoneall-raw` (5 523), `shubhamshendre` (4 251), `z3a4` (3 470),
`komutan234` (3 414), `tianndev` (3 289), `meid1981101-socks5` (2 668),
`proxyscraper` (2 216), `fusionproxies` (1 906), `dinoz0rg` (1 264).

The CN-aggregator repos (`meid1981101-ui/*`, `komutan234`, `Dahono`,
`denisyoya`) label their files `socks5` but mix in occasional HTTP
(80/8080/3128) rows; the downstream SOCKS5 handshake check in
`src/check/proxy-client.ts` filters them, so no parser change is needed.

### JSON sources enabled after parser extension

Three verified sources returned socks5 proxies in non-geonode JSON shapes.
`src/parse/json.ts` was extended on 2026-11-19 to auto-detect them, and all
three are enabled:

- **CharlesPikachu/freeproxy** — `proxies.json`, 11 782 entries (5 529 socks5,
  plus http/https/socks4 that the parser keeps under their own protocol).
  Shape: `{data:[{ip,port,protocol:"Socks5",…}]}`.
- **mauricegift/free-proxies** — `socks5.json`, 492 entries.
  Shape: `{proxies:["ip:port",…]}`.
- **proxytee.com** — `free-proxies.json`, 46 entries (25 socks5, 21 http).
  Shape: `{proxies:[{host,port,proxy_type:"SOCKS5",types:[{type:"SOCKS5"}],…}]}`.

### Sources disabled / flagged for review

- `advname-1..5` — HTTP 200 but 0 parsed (Cloudflare 403 challenge page).
  Flagged `enabled: false` pending parser/fetcher fix.
- `ebrasha-abdal-socks5` — 404, dead URL. Flagged `enabled: false`.
- `mrmarble-all` — 404, dead URL. Flagged `enabled: false`.
- `gfp-http/https/socks4/socks5` — HTTP 429 (rate-limited even with key).
  Left enabled; skipped quietly each cycle until the provider resets.

## Known scaling limits

- `OPP_MAX_NEW_PER_CYCLE` (default 120 000) is the real throughput ceiling:
  with 244 sources, the guaranteed per-source share is
  `min(120, floor(120000/244)) ≈ 491` candidates, so no source is starved.
- Fetch parallelism is hard-coded to 12 in `src/sources/fetcher.ts` with a
  60 s timeout — adding many sources grows wall-clock linearly. No env knob
  exists yet; bumping to ~24 would halve fetch time.
- `OPP_MAX_PER_SUBNET` (512) caps any single /24 in the published list. CN
  aggregator sources that draw from the same /24s will be truncated.
- Discover workflow (`src/cli/discover.ts`) is GitHub-only, capped at 120
  repos / 14 fixed paths / 100 search results per query; it cannot find
  non-GitHub sources and re-probes the same repos weekly. The 2026-11-19
  sweep above was done manually to work around this.
