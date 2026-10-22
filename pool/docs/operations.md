# Operations

How the refresh pipeline behaves, and the knobs that matter when things go
wrong.

## Cadence

`refresh.yml` runs every 15 minutes (`:07, :22, :37, :52`). One run is
`fetch → validate (matrix ×8) → merge → publish → commit`. A run takes
~5–10 minutes wall time including scheduling. `discover.yml` runs weekly.

## Sizing

The bottleneck is dead-proxy timeout, not throughput. With
`OPP_CONCURRENCY=250` and a 12 s budget, one shard checks roughly 1.5k–3k
candidates in 10–15 minutes, and re-checks a similar number of living
proxies. Four shards comfortably cover a 50k+ working pool on a 15-minute
cadence (the default matrix now runs 8 shards). To push higher, raise
`SHARD_COUNT` in the workflow matrix and `OPP_CONCURRENCY` together (both
free under the 20-concurrent-jobs limit of GitHub's Free plan).

## Knobs

| Concern                           | Knob                                                   |
| --------------------------------- | ------------------------------------------------------ |
| too many dead retries             | raise `OPP_RETRY_FAILED_AFTER_HOURS` (default 12)      |
| pool shrinks between runs         | raise `OPP_MAX_NEW_PER_CYCLE`                          |
| single /24 dominates the list     | lower `OPP_MAX_PER_SUBNET` (default 512)               |
| published lists look stale        | lower `OPP_PUBLISH_FRESH_MS` (default 4h)              |
| checks too aggressive             | lower `OPP_CONCURRENCY`, raise `OPP_STAGE1_TIMEOUT_MS` |
| echo targets blocked by a network | adjust `OPP_CHECK_TARGETS` order                       |

## Failure modes

- **A source 200s but yields 0 proxies** — `fetch-report.json` records it and
  the run logs a warning. This is how the historic `scheme://` parsing bug
  surfaced; treat it as a broken parser until proven otherwise.
- **A source 404s / rate-limits** — the run continues without it; disable it
  in `sources.yaml` if it stays dead.
- **`merge` fails after validate** — results are in artifacts; re-dispatch
  the workflow (`run_id` in `data/meta.json` identifies the run).
- **Pool drops to zero** — first check the echo targets (a public go/no-go
  toggle like a proxy-blocking CDN move produces exactly this), then
  concurrency and timeouts.

## State

`fs` store keeps `.state/pool.json.gz` plus the re-check queue; in Actions
both ride the `pool-state-*` cache, together with the ~8 MB country database
the geo step downloads on first use. If a cache is lost the pipeline rebuilds
from the next cycle's candidates — slower, self-healing — and re-downloads
the mmdb. With `OPP_STORE=postgres` the proxy state lives in `proxies`
(schema in `src/store/schema.sql`) and survives cache misses entirely.

## Published data

`merge` writes the pool's files into `data/` and the refresh workflow commits
them directly. The merged platform reads that directory: `hub` serves the
line lists and JSON under `/pool/*` and builds `/api/status.json` from
`stats.json`, `meta.json` and `benchmark.json`. There is no separate site
bundle to rebuild.

## History

`merge` appends one point per run to `data/history.json` (last 96 runs:
timestamp, total, per-protocol counts). It is kept as published history for
status consumers, so a shrinking pool is visible immediately rather than
after someone notices.

## Localisation of data

`data/` is the only committed artifact. Everything in `.state/` and `.work/`
is scratch and gitignored.
