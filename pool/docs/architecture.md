# Architecture

## Layout

```
sources.yaml              source registry (the only hand-edited data file)
src/
  config.ts               env-driven configuration
  log.ts                  structured-enough logging
  sources/                registry loading + HTTP fetching with redirects
  parse/                  plain-text and geonode-JSON parsers
  normalize/              dedup, sampling, deterministic sharding
  check/
    net.ts                buffered socket reader + TCP connect helpers
    proxy-client.ts       SOCKS5 / SOCKS4 / HTTP CONNECT clients
    targets.ts            echo target descriptors
    stage.ts              the checker: liveness phase + anonymity phase
    runner.ts             concurrency-limited batch runner
  geo/                    DB-IP auto-downloaded mmdb (maxmind) + ip-api fallback
  store/                  record model, fs snapshot + Postgres stores
  publish/render.ts       data/* rendering
  cli/                    fetch / validate / merge / publish / cycle / discover
  io/jsonl.ts             gzipped JSONL writer/reader (streaming)
.github/workflows/        ci, refresh, discover
test/                     node:test suites with local SOCKS5 + echo mocks
data/                     published artifacts (generated, committed)
```

## Data model

One canonical key per proxy: `proto://host:port` (`src/sources/types.ts`).
Checks produce `CheckResultRecord`s; the store merges them into
`ProxyRecord`s carrying rolling windows `uptime1h/24h/7d/30d`, a bounded
latency sample list, first/last-ok timestamps, provenance (`seenBy`) and geo.

Rendering keeps only records with a recent `lastOk` and applies a /24 cap so
one network cannot dominate the published list.

## Why the checker is built the way it is

- **Buffered reader instead of `sock.unshift`.** Reading a fixed number of
  bytes with push-back loses data when the readable is flowing; every
  partial read corruption traced back to it. `SocketReader` attaches one
  data listener at connect time and hands out exact reads.
- **Two request phases.** A single request cannot both decide liveness and
  grade anonymity: the most reachable targets (ipify) return no headers,
  and the header-bearing echoes (httpbingo, postman-echo) are the ones
  proxies block. Phase A is liveness + latency on the most permissive target;
  phase B grades anonymity by walking the JSON echo list until one answers.
- **Absolute-form fallback.** A growing family of open proxies are
  CDN-fronted and only speak `GET http://host/path`. For HTTP proxies the
  checker falls back to that form instead of failing the CONNECT.
- **Full-body reads.** Connect-then-stall proxies are not alive; a response
  counts only when the body is complete (content-length or terminal chunk).

## GitHub Actions split

Artifacts move between jobs (`candidates.jsonl.gz`, `results-<n>.jsonl.gz`),
the pool snapshot moves between runs through the `pool-state-*` cache. The
merge job is the only writer of `data/`, which keeps commits consistent and
one-run-per-snapshot.

Runner IPs are part of the design, not an implementation detail: they are
disposable, so neither the operator's addresses nor their provider's abuse
queue are exposed to the checked population. Public repositories don't pay
runner minutes on standard GitHub-hosted runners.
