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
```

The scheme in the line always wins over the entry's `protocol`.
`0.0.0.0`, `127.0.0.1` and invalid ports are rejected. IPv6 and hostnames are
not supported by the checkers and are skipped.

## What "json" accepts

A geonode-style payload:

```json
{ "data": [{ "ip": "1.2.3.4", "port": 1080, "protocols": ["socks5"] }] }
```

String ports are accepted (geonode sends them). When `protocols` lists
several, `socks5` beats `http` beats `socks4`.

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
