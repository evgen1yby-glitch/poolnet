# Zero-Traffic Hybrid Subscription Hub — Design (spec)

Date: 2026-10-14 · Status: **implemented, verified against unit suite** · Research basis:
`2026-10-14-*-research.md`

> **What this is, in one line.** A **decentralised FREE VPN platform**: a control
> plane that indexes and verifies freely published proxy configs and republishes
> them as a working VPN for anyone, without owning a single node and without
> ever carrying user traffic.

FREE is a deliberate triple reading, and all three are true of this design:

| Reading | Why it holds |
|---|---|
| **Free of charge** | No paid tier exists (§1). Nothing to pay for, nothing to upsell. |
| **Free as in libres** | Every payload is a plain list of public URIs. Any standard client can read it, any party can re-host or re-index it, and no proprietary protocol gates access. |
| **Free as in unblocked** | The product is access: RU/СНГ users get a subscription that works through RKN filtering. |

## 1. Goal and non-goals

### Goal

A self-hosted **control plane** that continuously discovers publicly published proxy
configurations, verifies them with a five-stage funnel, scores them on a reproducible
rubric, and publishes **tiered, pre-validated subscription payloads** that any standard
client (Hiddify, sing-box, v2rayNG, Karing, mihomo, Shadowrocket) can consume.

Target audience: **RU / СНГ**. This is a first-class design constraint, not a footnote —
it determines the protocol weighting, the vantage point value, and the failure posture
(§7).

### Why "decentralised" is the honest description

Not marketing — it follows from what the system actually does:

| Property | Mechanism |
|---|---|
| **No single provider to block** | The hub owns no nodes. It indexes third-party endpoints, so there is no `vpn.example.com` for a censor to null-route. |
| **No single source of truth** | Six independent upstreams (§4.4); any one can vanish without affecting the pool. |
| **No single artefact to trust** | Payload generations are content-addressed (`gen-<sha256[:12]>`), so the same pool always yields the same id, and a mirror can prove it serves the same content. |
| **No single point of failure at deploy** | Rollback is a pointer flip, not a re-render (§2.4). Any retained generation can be served instantly by any copy that holds it. |
| **No lock-in** | A payload is a text file. A user who dislikes this mirror exports the list and imports it anywhere else. |

### What "decentralised" does *not* mean yet (stated so the README can't overclaim)

The index itself is one server and one vantage point. That is a **roadmap** item, not a
property already achieved: mirror replication and multi-vantage verification are
described in §12. The honest claim today is *content-addressed, mirrorable, and
single-owner-free at the node layer* — not "censorship-proof".

### Non-goals (explicitly out of scope for this iteration)

| Non-goal | Why excluded |
|---|---|
| Serving user VPN traffic | Stated hard constraint. The server never becomes a node. |
| Paid / premium tier | Free only. The architecture leaves a seam (§9) but does not implement it. |
| Own nodes / hosting nodes | The hub aggregates third-party configs; it does not operate infrastructure. |
| Multi-region verification | Single vantage (Warsaw, PL). Region is recorded per measurement so the seam exists. |
| Anonymity for users | Opposite: the system stores an identifiable token per subscription. |
| Browser extension / mobile app | Future work; deep links to existing clients cover the need today. |

---

## 2. Architecture

Single server, five components, three adapters, one data store. Every component is a module
with one responsibility and a pure-function core so it can be tested without network.

```
                ┌──────────────────────────────────────────────────┐
   APScheduler  │                 PIPELINE (worker)                 │
   every 15 min │                                                   │
      │         │  fetcher → parser → prober → scorer → renderer    │
      │         │                    │            │            │     │
      │         │                  check        score        payload │
      └────────▶│                    └──────┬─────┘            │     │
                │                           ▼                   ▼     │
                │                    data/hub.db           data/gen-*  │
                │                    (SQLite)              (immutable) │
                └──────────────────────────────────────────────────┘
                                            │
   nginx ──── /sub/{token} ──── FastAPI (read-only) ────────────┘
                                ├── GET  /            landing page
                                ├── GET  /sub/{token} → 302 to live generation
                                ├── POST /api/v1/bot/...   (internal, HMAC)
                                └── GET  /metrics
   aiogram bot (long-poll, mock transport in tests)
```

### 2.1 Components

| Component | Responsibility | Interface | Pure core |
|---|---|---|---|
| `fetcher` | Pull raw text from `sources.yaml` (jsDelivr → raw → `t.me/s/`), ETag cache, per-source timeout/retry/backoff/UA, dead-source disabling | `async def fetch(cfg) -> list[RawItem]` | none (I/O) but fully injectable via a `HttpClient` protocol |
| `parser` | One URI line → `NodeRecord`, or a typed `ParseError`. Covers vless/vmess/trojan/ss/hysteria2/tuic/wireguard. **Unknown scheme = explicit error, never silent drop.** | `parse(uri: str) -> NodeRecord \| ParseError` | **fully pure** |
| `prober` | Five-stage funnel driving one long-lived `sing-box` process; per-stage concurrency; SSRF guard | `async def probe(records) -> list[ProbeResult]` | funnel logic pure; I/O behind `CoreDriver` protocol |
| `scorer` | 0–100 from the rubric in §5 + cross-run availability history | `score(node: NodeRecord, history: History, probe: ProbeResult) -> Score` | **fully pure** |
| `renderer` | Score → payloads for 3 formats × N tiers × 2 cores. Emits unique tags, validates via `sing-box check` before publish | `render(tier: Tier, core: Core, fmt: Format) -> bytes` | **fully pure** except the `check` hook |
| `gate` | Telegram membership with cache + `chat_member` invalidation | `is_member(user_id) -> bool` | cache policy pure |

### 2.2 The three adapters (depend on the components, never the reverse)

| Adapter | Role |
|---|---|
| `api` (FastAPI) | Read-only subscription serving. **Never** triggers pipeline work on the hot path. |
| `bot` (aiogram 3.31) | Optional delivery channel. Behind a `BotTransport` protocol → mock in tests. |
| `cli` | `python -m hub verify-log`, `hub publish`, `hub rollback`, `hub serve` |

### 2.3 Data store

**SQLite** (`data/hub.db`, WAL mode). PostgreSQL would be over-engineering on a single
12-core/62 GB box; SQLite handles the write rate with room to spare and the whole DB is
one file to back up.

| Table | Rows | Growth | Purpose |
|---|---|---|---|
| `nodes` | ~5k | stable | IR + `dedup_key = sha256(proto\|host\|port\|credentials)`, current score, last success, first seen |
| `checks` | append-only | ~5k/run | probe results; **retention: 30 days**, pruned by the pipeline |
| `sources` | ~20 | stable | URL, cadence, ETag, consecutive-empty-rounds, disabled flag |
| `subscriptions` | 1/user | linear | `token` (unique), `telegram_user_id` (nullable), `status`, `created_at`, `last_seen_at` |
| `publishes` | ~4/day | trivial | `generation`, `sha256`, `tier`, `core`, `fmt`, `node_count`, `created_at` — the rollback index |
| `events` | NDJSON on disk | unbounded until rotated | raw audit log, append-only, rotated daily, 30-day retention |

**Why NDJSON next to SQLite:** the check log is an append-only fact table with no index
needs. SQLite would make it a row-scan burden; NDJSON writes in O(1) and is the source of
truth for retroactive score recomputation.

### 2.4 Immutable generations (the rollback primitive)

Every pipeline run produces `data/gen-<sha256>/...` and flips a single pointer
`data/gen-current` **atomically** (`os.replace`). The API resolves the pointer, never a
path built from mutable state.

```
data/
  gen-9f2a…/  curated.base64  verified.base64  singbox.json  country-RU.base64  manifest.json
  gen-4e1c…/  …
  gen-current → gen-9f2a…        (symlink or small JSON pointer file)
  gen-4e1c… kept for 3 generations → instant rollback = repoint
```

`manifest.json` records `{generation, sha256, created_at, tiers: {name: {nodes, sha256}}}`.
The pipeline **refuses to publish** if any candidate payload fails `sing-box check`, has
zero nodes, or drifts >40% in node count vs the previous generation. On refusal the old
pointer stays live — **fail-open, never fail-closed** (§7).

---

## 3. Subscription URL and access model

```
GET /sub/{token}
  → resolve subscription row by token (indexed lookup, no other query)
  → if unknown/blocked  → 404 with a body that explains, no subscription content
  → else → 302 to /data/gen-current/<tier>.<ext>?v=<generation>
```

**Rate limiting:** token-bucket per token (240/h) **and** per IP (600/h), enforced by a
small in-process limiter with an LRU of hashed IPs (no PII stored). Enumeration is
therefore economically useless: a leaked token id can be scanned, but it yields the same
public payloads anyway — the content is not secret, only the *subscription identity* is.

**Why a public token and not a signed URL:** the operator chose the simple model; the
content is public by nature (it is a list of public proxy configurations), so the token
protects against *enumeration-driven load*, not against confidentiality. This is
documented, not hidden.

### Response headers (per verified client spec)

```
Content-Type: text/plain; charset=utf-8        # or application/json for sing-box
profile-update-interval: 6
subscription-userinfo: upload=0; download=0; total=0; expire=0
profile-web-page-url: https://<domain>
support-url: https://<domain>/help
content-disposition: attachment; filename="hub.txt"
```

- `subscription-userinfo` always carries **both** `total` and `expire` — Hiddify silently
  discards the entire block (and then also `support-url`/`profile-web-page-url`) otherwise.
- `expire=0` is a real timestamp, not "unlimited"; a large far-future value is used if a
  meaningful expiry is ever introduced.
- `profile-update-interval` is an integer in **hours**.

---

## 4. Pipeline detail

### 4.1 Stage parameters (from verified industry practice)

| Stage | Concurrency | Timeout | Rationale (source) |
|---|---|---|---|
| 1. TCP connect | 200 | 2 s | cheapest gate; drops ~40% of raw |
| 2. TLS handshake, real SNI | 200 | 3 s | `xray tls ping` / `openssl s_client` semantics |
| 3. `sing-box check` | unbounded | µs | CPU-only, ~40 µs/config (v2go measurement) |
| 4. HTTP-over-proxy, 2 rounds 45 s apart | **100** | 5 s | Au1rxx + AutoMerge; >500 empirically degrades (v2go) |
| 5. Reputation/geo, published nodes only | 20 | — | API free tiers (proxycheck 1k/day) |

Expected funnel on this box: ~5k raw → ~3k TCP → ~2k TLS → ~700 valid → **~250 verified**.
Only the survivors are ranked and published.

### 4.2 The sing-box driver

One long-lived `sing-box` process holding N outbounds and N tagged SOCKS inbounds, driven
over its config file + process lifecycle. Chosen over subprocess-per-node because:

- subprocess-per-node is ~67 MB RSS × C (at C=100 → 6.7 GB) — wasteful when the whole
  in-process model is ~67 MB;
- a single process keeps tag uniqueness and config validation in one place;
- the funnel's concurrency limits (≤200) are socket-bound, not process-bound.

Nodes that fail sanity (private-range resolution, link-local dial) are rejected before the
driver ever sees them — the SSRF guard — and a **quarantine netns path** is reserved for
v2 (sing-box 1.12+ `network_namespaces`).

### 4.3 Security checks (the differentiator)

Beyond reachability, each surviving node must pass:

| Check | Method | Reject on |
|---|---|---|
| **Injection canary** | fetch a page containing a per-run unique token; diff bytes vs a known-clean baseline | any added `<script>`, `<iframe>`, `meta http-equiv=refresh`, or modified body |
| **Certificate substitution** | capture the served leaf chain; verify SPKI pin and CT/SCT presence | valid-but-not-CT-logged cert, SPKI mismatch |
| **DNS integrity** | resolver ASN ≠ exit ASN, or a canary-domain answer we control returns wrong | mismatch |
| **Transparent-proxy** | exit IP through node == exit IP direct | equality |
| **Geo integrity** | `cdn-cgi/trace` `loc=` vs the node's advertised country | mismatch (advisory in v1 — penalise, don't hard-reject; CDN-fronted exits false-positive) |
| **Reputation** | `proxycheck.io` `risk` score, on published nodes only | `risk >= 67` ("dangerous"), or `type: "Compromised Server"` |

Levels A (injection) and B (cert/CT) are the parts most aggregators skip; v1 ships
injection + reputation, with cert/CT as the first follow-up. See the open question in §10.

### 4.4 Ingest politeness (protects the sources and us)

- `raw.githubusercontent.com` first (verified reachable, unmetered), jsDelivr second,
  REST API only with a PAT — **never** anonymous (the anonymous budget was already
  exhausted today: `remaining: 0`).
- Conditional requests (`ETag`/`If-None-Match`) on every source; a 304 costs nothing.
- Per-source timeout, 3 retries with exponential backoff, min 10 s spacing between pulls
  of the same source.
- A source returning 20 consecutive empty rounds is auto-disabled (AutoMerge's rule).
- New (never-seen) sources are **quarantined**: they may contribute at most 10% of the
  published pool until they survive 10 rounds. Anti-Sybil.

### 4.4.1 Operator safety rule: the live network is off-limits (hard constraint)

This server is shared working infrastructure. **No test, probe, or experiment that
establishes a VPN/proxy connection may alter the host's live network.** Concretely,
forbidden on the host network namespace, at any time:

| Forbidden | Why |
|---|---|
| Adding, deleting, or changing routes / default gateway | Breaks connectivity for everything else on the box |
| Writing system DNS config (`/etc/resolv.conf`, `systemd-resolved`) | Leaks and breaks name resolution for other services |
| Opening a listening port on a routable interface | Exposes a SOCKS/HTTP proxy to the world — the fastest way to get the host blocked and to turn the server into an open relay |
| `iptables`/`nftables` NAT or REDIRECT rules on the host | Same as above, plus it silently reroutes existing traffic |
| Running the prober driver as root on the host namespace | A bug then has root and the host network |

How probes are run instead:

1. **Default — mock only.** `CoreDriver` is a Protocol; unit tests use a scripted fake
   and no socket is ever opened. This is the mode `pytest` runs in.
2. **Real-node runs — `unshare -rn`** (private network namespace + loopback, *no default
   route*, private iptables). Inside that namespace a listener on `127.0.0.1` is
   unreachable from outside and there is no route to leak to, so both failure modes above
   are structurally impossible. Outbound to third-party nodes requires an explicit
   `--veth`/slirp setup the operator enables deliberately, never by default.
3. **Before/after assertion.** Any test that does touch a network namespace records
   `ip route` and `ss -ltn` on the host before and after and fails if either changed.

This is also why the sing-box driver is the one component that is *not* part of the
default test suite: it is the only one that needs a binary and a socket.

---

## 5. Scoring

Reproducible 0–100, published per node so a score is auditable. Weights (AutoMerge's
published rubric, adapted for a RU/СНГ audience):

| Factor | Weight | Computation |
|---|---|---|
| `latency` | 25 | `max(0, 25 × (1 − p50_http/1000 ms))` |
| `availability` | 20 | `20 × (successful rounds / 30 days)`, EWMA-weighted — **the single best predictor of tomorrow's uptime** |
| `jitter` | 15 | `max(0, 15 × (1 − stdev/300 ms))` |
| `source_history` | 10 | source 30-day pass rate |
| `protocol_history` | 10 | per-protocol historical reliability over the last 30 days |
| `throughput` | 10 | `min(10, 10 × speed/2 MBps)` |
| `fingerprint_resistance` | 5 | REALITY/XTLS-Vision/uTLS > plain TLS > none; +bonus on 443 |
| `geo_integrity` | 5 | penalty if `trace.loc` contradicts the advertised country |

`protocol_history` is the RU-critical column: it must encode that VLESS+Reality is the
gold standard and Trojan/SS/WG are heavily detected in RU. The weights live in a
**versioned YAML** (`config/scoring.yaml`) — changing the rubric bumps a version and
history is keyed by it, so scores remain comparable.

Tiers built from the score:

| Tier | Size | Definition |
|---|---|---|
| `curated` | 30 | top score, weighted toward RU/CIS reachable, protocol-robust |
| `verified` | 150 | passed the full funnel (all security checks) |
| `country-<CC>` | ≤100 | shard, self-similar to `verified` |

Each payload is chunked to **≤200 nodes** (v2rayNG import freezes above ~1k; 200 is the
practised ceiling) and validated with `sing-box check` before publish.

---

## 6. Renderer

Three output formats, two core targets.

| Format | Consumer | Notes |
|---|---|---|
| `base64` | v2rayNG, v2rayN, Shadowrocket, NekoBox | newline-separated share links, base64-wrapped |
| `singbox.json` | sing-box official, Hiddify, v2rayN, Happ | full config incl. `route`/`dns` |
| `clash.yaml` | mihomo, FlClash, Karing, Clash Verge Rev | `proxy-groups` with `url-test` |

Renderer invariants (all verified traps):

1. **Tags are minted server-side**, globally unique per payload: `n<seq>-<proto>-<cc>`
   (e.g. `n001-vless-nl`). Duplicate tags are a hard `FATAL` in sing-box and illegal in
   mihomo. Source-supplied `#fragment` names are never reused verbatim.
2. **`interval` is format-specific**: `"10m"` for sing-box (Go duration), `300` for mihomo
   (int seconds). Two renderers, one model.
3. `urltest` uses `interval: "10m"`, `tolerance: 150`, `idle_timeout: "30m"`,
   `interrupt_exist_connections: false` — 150 ms tolerance prevents micro-jitter from
   breaking long-lived connections; 10 m interval prevents client sluggishness on large lists.
4. **`client_core` parameter**: `xray` vs `sing-box`. XHTTP nodes are dropped when
   `client_core=sing-box` because upstream sing-box does not support XHTTP
   (SagerNet/sing-box#3550). Hysteria2 conversely requires sing-box/mihomo and is dropped
   for Xray-only clients.
5. **`cache_id` in `experimental.cache_file`** is set to the hash of the payload's node
   set, so a rotation invalidates fake-IP caches (FlClash #734).
6. `rule_set` entries carry `download_detour: "direct"`; route order is
   `sniff → hijack-dns → dns-out → private → geoip/geosite-ru → resolve → proxy`.
7. No `allowInsecure` anywhere (hard failure in Xray 26.x).
8. Every payload passes `sing-box check` before publish; a failing payload is discarded,
   never published.

---

## 7. Failure posture and observability

**Fail-open, always.** The worst outcome is serving *nothing*. The second worst is serving
a broken payload. The acceptable outcome is serving yesterday's valid payload.

| Failure | Behaviour |
|---|---|
| All sources down | Reuse the last generation; alert. |
| New generation invalid | Discard; keep the previous pointer. |
| `sing-box check` fails | Node dropped from the payload (not the whole payload) unless too many fail |
| Reputation API down | Skip reputation for this run (don't reject nodes for missing data) |
| Bot/Telegram down | Subscriptions still work — bot is a channel, not a dependency |
| Disk full | Pipeline pauses; old generations pruned aggressively; alert |

### SLOs

| SLO | Target | Alert |
|---|---|---|
| Payload age | < 30 min p95 | page at > 60 min |
| Payload validity | 100% published payloads pass `sing-box check` | page on any failure |
| Node count drift | < 40% vs previous generation | warn |
| API availability | 99.5% / month | page |

### Metrics (`/metrics`, Prometheus text format)

`hub_payload_age_seconds`, `hub_generation_number`, `hub_nodes_total{tier}`,
`hub_stage_survivors{stage}`, `hub_probe_latency_seconds{stage,quantile}`,
`hub_publish_failures_total`, `hub_external_429_total{api}`, `hub_sources_active`,
`hub_subscription_requests_total{code}`, `hub_uptime_seconds`.

### Dead-man's-switch

An external push monitor (Uptime Kuma push, or a simple cron hitting `/healthz/ping`) is
mandatory: the pipeline, not the users, must detect its own death. This is the lesson of
GitHub Actions' silent 60-day schedule disabling.

---

## 8. Telegram bot (optional channel)

- **aiogram 3.31**, **long-polling** by default (buffers updates up to 24 h — survives a
  dead server, unlike a webhook), webhook-mode supported behind a flag.
- **`BotTransport` protocol** so the whole bot is testable without Telegram. Mock transport
  in CI.
- **Gating with `getChatMember`**, because the method is only guaranteed to work when the
  bot is an **administrator** of the channel:
  - positive results cached 10 min per `(user_id, chat_id)`;
  - `chat_member` updates invalidate instantly (`old ∈ {member,admin,creator}` and
    `new ∈ {left,kicked}` → revoke);
  - the "check subscription" button is rate-limited per user (1 per 30 s);
  - **429 counts and `retry_after` distribution are first-class metrics** — Telegram's
    silent throttling is observable only through them.
- Broadcasts are a background job with their own token bucket (≤25 msg/s global, 1/s per
  chat) and never share the interactive rate budget.
- **Telegram is a delivery channel, never the single point of failure.** Every link the
  bot hands out must also be reachable from the web landing page and from the README.

---

## 9. Testing strategy (TDD)

Pure functions get table-driven tests with no mocks. I/O sits behind protocols and is
injected.

| Module | Test style |
|---|---|
| `parser` | Golden table: every supported scheme + ~30 malformed inputs (percent-encoding traps, missing ports, bad base64, duplicate query keys, unicode fragments) |
| `scorer` | Property tests on the rubric (bounded 0–100, monotonic in each input), and rubric-version pinning tests |
| `renderer` | **Golden files + `sing-box check`** on every fixture: unique tags, format-specific `interval`, core-filtering, byte-comparison against a stored fixture |
| `prober` | `CoreDriver` faked with scripted responses; funnel ordering, concurrency limits, SSRF guard, quarantine |
| `gate` | Mock transport: cache hit/miss, `chat_member` invalidation, 429 backoff, blocked-user path |
| `api` | FastAPI TestClient: unknown token, blocked token, pointer resolution, rate limit, headers present and correct |
| `pipeline` (integration) | End-to-end on 5 real nodes with a real `sing-box`, marked `--run-slow`, off by default |

Coverage gate: 90% on `parser`, `scorer`, `renderer`, `gate`; 75% elsewhere.

---

## 10. Open questions for the operator

1. **Tier shape** — I propose `curated` (30) / `verified` (150) / `country-<CC>` (≤100).
   For a RU/СНГ audience an alternative is a **protocol tier** (`reality` / `hysteria2` /
   `mixed`), which matches how users actually choose nodes. My recommendation: keep both —
   protocol is the primary split, geography the secondary. Confirm?
2. **Security levels in v1** — injection canary + reputation ship now; cert/CT pinning is
   the first follow-up. Acceptable?
3. **Python package layout** — a `src/` layout with `pyproject.toml` + `uv`/`pip` venv, or
   a flat layout? Recommend `src/` + `pip` (no new toolchain on the server).
4. **Deployment** — `systemd` units (`hub-worker.timer`, `hub-api.service`,
   `hub-bot.service`) under a dedicated unprivileged user, or Docker Compose? Recommend
   systemd (no docker-group friction, already confirmed passwordless sudo is available).

---

## 12. Roadmap to real decentralisation

The claim "decentralised FREE VPN platform" is earned at the node layer today and at the
index layer only partially. This section is the deliberate, ordered path from the second to
the first — each step is independently useful and none requires a rewrite.

| # | Step | What changes | Why it matters |
|---|---|---|---|
| 1 | **Mirrorable generations** (already true) | Payloads are content-addressed under `gen-<sha256[:12]>` | Two operators publishing the same pool produce provably the same artefact. Nothing to do — it is a property of `_publish`. |
| 2 | **Signing** | Publish a detached minisign/ed25519 signature over the manifest, and put the public key in the repo | A mirror proves it served *this* content. Blocks the "evil mirror swaps in dead nodes" attack, which is the first thing an adversary does to a mirror network. |
| 3 | **Mirror registry** | A static, signed list of mirrors in the repo; a client tries them in order until one answers | Removal of the single-owner failure mode at the index layer. A mirror is a `git clone` + `pip install` + one systemd unit. |
| 4 | **Multi-vantage verification** | Extend `ProbeResult` with `vantage_id` and let several operators exchange signed results via the event log | One vantage reports a node alive; a node blocked in RU is alive everywhere else. This is the single highest-value measurement change for our audience. |
| 5 | **Gossip / discovery** | Peers exchange `(dedup_key, stage_reached, score)` events; the store ingests foreign events with a trust weight | The pool stops depending on any fixed source list. Becomes genuinely P2P. |
| 6 | **First-party client** | Flutter or Electron app that speaks the payload format directly and resolves mirrors itself | Removes the dependency on Hiddify/v2rayNG feature cadence; makes the platform self-describing. Last, because today's clients already do this job well. |

Sequenced by value-per-unit-effort, not by ambition. Signing first because it is a day of
work and it is the prerequisite for trusting anybody but us.

---

## 13. Repository layout

```
/home/dev/freevpn/
├── docs/
│   ├── LEGAL.md
│   └── superpowers/specs/*.md
├── src/hub/
│   ├── __init__.py
│   ├── models.py          # NodeRecord, ProbeResult, Score, enums
│   ├── parser.py          # URI → NodeRecord
│   ├── fetcher.py         # sources.yaml → RawItem
│   ├── prober.py          # five-stage funnel + CoreDriver protocol
│   ├── driver.py          # sing-box subprocess driver
│   ├── scorer.py          # 0–100 rubric
│   ├── renderer.py        # payload generation
│   ├── store.py           # SQLite schema + queries
│   ├── pipeline.py        # orchestration + publish/rollback
│   ├── api.py             # FastAPI app
│   ├── bot.py             # aiogram app + BotTransport protocol
│   ├── gate.py            # membership cache + invalidation
│   ├── metrics.py         # Prometheus registry
│   └── cli.py             # python -m hub
├── config/
│   ├── sources.yaml       # versioned source list
│   ├── scoring.yaml       # versioned rubric weights
│   └── settings.py        # env-driven settings (pydantic-settings)
├── tests/
│   ├── fixtures/          # golden payloads, node lists, malformed URIs
│   └── test_*.py
├── data/                  # runtime: hub.db, gen-*, NDJSON
└── tools/                 # sing-box binary (downloaded, not vendored)
```
