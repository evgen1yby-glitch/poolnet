# Zero-Traffic Hybrid Subscription Hub — Research Findings (working notes)

Research date: 2026-10-14. This document captures verified facts that constrain the design.
Every claim marked **[verified]** has a primary source; **[estimate]** is engineering judgement.

---

## 0. Constraints received from the operator

| Constraint | Value |
|---|---|
| Target audience | **RU / СНГ** — pools and protocols designed for RKN circumvention |
| Monetization | **Free only** in this iteration; premium tier is a future possibility, not designed now |
| Infrastructure | **One dedicated server** — 12 × AMD Ryzen 5 PRO 4650G, 62 GB RAM, 465 GB free disk, Ubuntu 24.04, Python 3.12, Node 22, Docker (needs sudo), 2 × public IPv4, **no IPv6**, located **Warsaw, PL (AS201814 MEVSPACE)** |
| Exposure | Public domain, direct access (HTTPS via reverse proxy on this server) |
| Access model | Simple public token in the URL (`/sub/{token}`) |
| Telegram bot | Build code with a mock transport; no real bot token yet |
| Traffic | **Server must never proxy user VPN traffic** — control plane only |

---

## 1. Server reality check (measured today)

- GitHub anonymous REST API is **already exhausted** (60/hr, `remaining: 0`). → Sources must be read via `raw.githubusercontent.com` (unmetered, verified 200 OK) or jsDelivr, never via the REST API.
- `curl https://www.gstatic.com/generate_204` → **204 OK** in <1 s. Confirms canary reachability from this vantage.
- `ulimit -n` = 1,048,576 → socket concurrency is not a limit.
- Docker daemon needs `sudo`; passwordless sudo available.
- Ports 80/443 free; 5432 (Postgres) and 6379 (Redis) already bound by other services.

**★ Engineering consequence:** this server is a *good* verification vantage for RU/СНГ (Warsaw → Moscow ≈ 10–15 ms). The prober is the only component that earns its keep here; API + bot are trivial loads that can share the box.

---

## 2. GitHub Actions as a scheduler — NOT viable [verified]

| Fact | Source |
|---|---|
| `schedule` events are **delayed during high load**, and **"some queued jobs may be dropped"** | GitHub docs, *Events that trigger workflows* |
| HyperPing measured **64%** of 15-minute cron slots produced a run over 7 days; **median start delay 7.4 min** | hyperping.com |
| **Schedules are auto-disabled after 60 days of repo inactivity — silently, with no notification** (public repos) | GitHub discussions #184653; real outage May 3 → Sep 17 2026 |
| Self-hosted runners now bill **$0.002/min** in private repos (since 2026-03-01) and consume plan quota | GitHub changelog |
| Minimum runner version enforced fully since **2026-09-25** | GitHub changelog |

**Conclusion:** the original concept's "GitHub Actions runs the scraper every 15–30 min" is the weakest point in the plan. GitHub Actions may remain a *secondary/backup* trigger on a public repo, but the primary scheduler must be `systemd`/`APScheduler` on the owned server, with a dead-man's-switch.

---

## 3. The verification funnel — settled industry practice [verified]

Au1rxx/free-vpn-subscriptions (the incumbent, hourly, most transparent) publishes this funnel:

| Stage | Per-node cost | Drop | Proves |
|---|---|---|---|
| 1. TCP reachability | ~1 RTT | ~40% of raw | host alive |
| 2. TLS handshake (TLS/REALITY/WS-TLS) | ~2 RTT | further | real TLS endpoint, SNI accepted |
| 3. Translate to sing-box outbound + **`sing-box check`** | CPU (µs) | 2600 → 840 | config valid — **this is where client-crashing params die** |
| 4. **HTTP-over-proxy** via per-node local SOCKS5 inbound | ~3–5 RTT | 840 → ~280 | tunnel actually carries data |
| 5. Two rounds 45 s apart, keep nodes with ≥50% success | ×2 | — | flapping-node rejection |
| 6. Rank by median HTTP RTT | — | — | ordering |

Live numbers (2026-10-14): 17 sources → ~4,800 raw → 2,900 TCP → 2,600 TLS → 840 valid → 280 verified → **top 150 published**.

**Throughput law [verified]:** v2go measures **~40 µs CPU per config** during live testing; the pipeline is **socket-bound, not CPU-bound**. Concurrency >500 empirically *degrades* results (v2go README). FastNodes: 2,682 deep checks in 161 s ≈ 1,000/min. subs-check: `concurrent: 50`, `timeout: 5000`, `min-speed: 512 KB/s`, `download-mb: 20`, speed-test concurrency deliberately halved to 20 because parallel speed tests corrupt each other.

**Production pass rate [verified]:** AutoMergePublicNodes snapshot 2026-10-14: 107 sources → 97,972 raw → 27,169 deduped → 3,000 TCP-reachable → **66 usable (2.2% end-to-end yield)**.

**Design rule:** budget the expensive stages (speed test, reputation API) against the ~2–4% survivors, never the raw candidate count. Cap speed tests to a fixed top-N — at 15-min cadence on a 10k pool, uncapped 20 MB speed tests would consume ~25 TB/month.

---

## 4. Canaries and the security layer — the differentiator [verified]

Standard canary pair:
- `http://www.gstatic.com/generate_204` → expect **204**. Chosen by Android/ChromeOS for captive-portal detection precisely because a portal returns 200/203/redirect instead.
- `https://www.cloudflare.com/cdn-cgi/trace` → 200 + `ip=`, `loc=`, `colo=` — gives **exit geo/ASN in the same request** as the health check. Preferred over ipinfo to avoid rate limits.

Cross-vendor canary set (KaringX/karing#635): `connectivitycheck.gstatic.com`, `clients3.google.com`, `www.msftconnecttest.com`, `cp.cloudflare.com`, `captive.apple.com/hotspot-detect.html`, `network-test.debian.org/nm`, `detectportal.firefox.com/success.txt`.

**Adversarial baseline [verified]:**
| Finding | Source |
|---|---|
| **84% of free VPN apps leaked traffic**, 18% no encryption, 67% tracking libs | ICSI/CSIRO 283-app study |
| **16% of non-transparent proxies injected JS**, **4% performed TLS interception** | same study |
| ~800 free-VPN apps with malware/suspicious behaviour | Zimperium zLabs (2025) |

**The incumbent's own admission:** Au1rxx README: *"Free nodes see all your traffic."*

**Detections most aggregators skip (our opportunity):**
| Attack | Detection |
|---|---|
| HTML/JS injection | Request a page containing a **per-run unique token**; diff returned bytes vs known-clean baseline. Direct counter to the 16% cohort. |
| Certificate substitution | Capture served leaf chain; verify SPKI pin vs expected hostname + CT-log/SCT consistency (RFC 9162). **A valid-but-not-in-CT cert is the strongest single signal of interception.** `xray tls cert` / `certificate_public_key_sha256` provide primitives. |
| DNS tampering | Resolver ASN ≠ exit ASN = split traffic. Plus a canary domain whose correct answer we control. |
| Transparent proxying | Exit IP via node == exit IP direct → not actually proxying. |
| Geo lying | **Trust `cdn-cgi/trace` `loc=`, never the `#US` remark.** nexus-nodes applies a Cloudflare CDN-IP override because CDN-fronted exits otherwise mislabel as a CF PoP country. |
| Freshness attack | One perfect 15-min window then malicious. Counter: cross-run presence streaks — **one good run is worth almost nothing.** |

**Pool-poisoning vectors:** source flooding (counter: per-run test cap + disable source after ~20 empty rounds), Sybil score manipulation (counter: cap per-source contribution to published pool, weight source longevity not throughput), geolocation lying, canary poisoning (counter: rotate canary hostnames, require quorum across independent vantage points).

**SSRF guard is mandatory:** AutoMerge rejects resolved IPs in private ranges and `169.254.169.254`. A poisoned node entry with an RFC1918 host turns the verifier into an internal network scanner.

---

## 5. Scoring — the only published rubric [verified]

AutoMergePublicNodes `config/scoring.yaml` — reproducible 0–100:

| Factor | Weight |
|---|---|
| latency | 25 |
| source_history (per-source 30-day pass rate) | 20 |
| jitter (RTT variance across rounds) | 15 |
| protocol_history (per-protocol reliability) | 15 |
| tcp (stage-1 stability) | 10 |
| speed | 10 |
| fingerprint_resistance (REALITY/uTLS present, 443-port bonus) | 5 |

Profiles shipped: `scoring.low_latency.yaml`, `scoring.stability.yaml`, `scoring.source_quality.yaml`.
Reputation APIs: **proxycheck.io v2** returns `type: "Compromised Server"` — directly actionable for a free-node hub (1,000 queries/day free); **IPQS Proxy Detection** fraud thresholds `<75 suspicious, <85 high risk, <90 frequent abuse` (5,000 lookups/month free).
**Rule:** version the scoring config and publish the per-node breakdown so a score is auditable rather than asserted.

---

## 6. Client / payload constraints [verified]

| Fact | Source |
|---|---|
| **Payload size is a functional constraint, not a bandwidth one.** mahdibland README: *"the number of nodes is too high and your client will crash if you import them"* | mahdibland/V2RayAggregator |
| sing-box issue #1807: a config with many outbounds in nested `urltest`/`selector` groups **crashes the client** | SagerNet/sing-box |
| `urltest` defaults: `interval: 3m`, `tolerance: 50ms`, `idle_timeout: 30m`, `url: http://www.gstatic.com/generate_204` | sing-box docs |
| MatinGhanbari splits into **39 subscriptions of ≤200 nodes each** — client-compatibility practice | MatinGhanbari/v2ray-configs |
| VPNpool: **every generated config goes through `sing-box check`; broken nodes are dropped; an unusable result falls back to the previous config** | roman-png/VPNpool |
| Client-side re-ranking: ship the payload with a `url-test` group so the client re-tests live (**Au1rxx uses 300 s interval**) | Au1rxx |

**Design rule:** publish **tiered, narrow payloads** (e.g. top-30 curated + top-150 verified + country shards), never a raw 50-node dump. Validate every emitted config with `sing-box check` before publish; keep the previous generation for rollback.

---

## 7. Delivery / hosting economics [verified]

| Fact | Value |
|---|---|
| Cloudflare **R2 egress = $0.00/GB, always, at any volume** | Cloudflare R2 pricing |
| Same 14 TB/month on AWS S3+CloudFront ≈ **$1,200/month** | egresscost.com |
| Cloudflare Workers Free = **100,000 req/day hard cap** (Error 1027); can be configured **fail-open** | Cloudflare docs |
| **Static asset requests are unmetered**; only Functions/Worker invocations count | Cloudflare docs |
| Cloudflare ToS prohibits caching a **disproportionate percentage of non-HTML content** on a proxied zone | Cloudflare SSA/CDN terms |
| Serving cached large JSON: ~**14,000 req/s** (fastify-big-json case, 4 vCPU) — our load is nowhere near this | fastify/benchmarks |

**Note:** the operator owns the server, so `$0` third-party spend is not a hard requirement — but the same principles (unmetered static delivery, immutable generations, fail-open) still apply. On an owned box the delivery path is nginx serving pre-rendered files.

---

## 8. Telegram funnel — three independent failure points [verified]

| Finding | Impact on the original concept |
|---|---|
| **Telegram is under de-facto blocking in Russia since 14–15 March 2026** (availability ~80%, ~6,000→12,000 complaints on Сбой.рф); Apple pulled alternative client Telega in Apr 2026; RKN confirmed "successive restrictions" 10 Feb 2026 | **Telegram cannot be the delivery backbone.** Every key and subscription URL needs a web mirror. |
| **Rewarding GitHub stars violates GitHub's Acceptable Use Policy** (reinforces the independently-found StarScout finding) | The "invite a friend / star → exclusive nodes" viral mechanic must be non-rewarding. |
| Roskomnadzor restricted **439 VPN services by mid-Jan 2026, 469 by end-Feb 2026**; VPN-advertising fines since Sep 2025: **200,000–500,000 ₽ for legal entities** | Real legal exposure. Needs an explicit, documented posture in the design. |
| **`getChatMember` is only guaranteed to work if the bot is an administrator in the chat**; undocumented limits; community measurements ~20–30 req/s for `getChatMembersCount`, `getChatMember` noticeably tighter; a real case of a bot temporarily banned for spam `getChatMember` calls | **Cache + `chat_member`-update invalidation is a correctness requirement**, not an optimization. |
| Bot API broadcast: **~30 msg/s global**, ~1/s per private chat, 20/min per group. `getUpdates.limit` default 100. Webhook bodies >1 kB gzipped since 7.5. 1M users ≈ 9.3 h to broadcast. | Bot architecture must be long-poll-first with leasing, and broadcasts must be a background job with its own rate budget. |
| aiogram **3.31.0 (2026-08-26)** is the best-maintained Python choice; Telethon archived read-only **21 Feb 2026**; Pyrogram unmaintained since 2023 (Kurigram is the maintained fork) | Library choice: **aiogram 3.x**. |
| Mini App origin lockdown **auto-enforced 20 July 2026** — methods called from a foreign origin are blocked | Host any Mini App on a domain we own. |
| Stars are effectively **unavailable for a Russian paying audience** (RU cards declined by Apple/Google/Stripe) and carry documented treason-prosecution tail risk | Confirms "free only" for now is the right call. |

---

## 9. Reference projects (what to learn, what to avoid)

| Project | Take | Avoid |
|---|---|---|
| **Au1rxx/free-vpn-subscriptions** (incumbent, ~942★) | The reference funnel + canary pair + delivery model | US/JP/SG geo bias; no security verification — **our gap** |
| **LeilaoMi/AutoMergePublicNodes-Optimized** | The only published 0–100 rubric; source auto-disable after 20 empty rounds | — |
| **beck-8/subs-check** | Parameter defaults (concurrency/timeouts/min-speed); `save-method` abstraction | — |
| **roman-png/VPNpool** | **Config validation + rollback**: every config through `sing-box check`, broken nodes dropped, fall through to previous config. Also 9-UA fan-out and offline-cache reuse with a Telegram warning at ≥3 days | — |
| **kereal/rs8kvn_bot** | Bot+bscription-server separation; **240 s single-flight cache** (stampede control); web↔bot dependency isolation | — |
| **7Sageer/sublink-worker** (MIT) | Storage-adapter abstraction; **"subscription links are only used during conversion, not stored or logged"** privacy posture | — |
| **tindy2013/sub-converter** (17.1k★) | `config=` external-URL = config version pinning; `\|`-joined multi-source merge | Default creds; no auth layer |
| **mahdibland/V2RayAggregator** | Tiered payloads | US-only vantage bias; payload sizes that crash clients |
| **Danialsamadi/v2go** (Go, 154★) | Embedded core, no subprocess, no open ports, 40 µs/config | Unverified marketing claims |
| **rtwo2/FastNodes** | Multi-vantage (3 regions) verification; presence streaks; skips CF-fronted hosts | — |
| **sub-store-org/Sub-Store** (AGPL-3.0) | The "operation pipeline" abstraction shape | **Do not copy code** — AGPL source-offer obligation |
| **careywang/sub-web** (MIT) | Thin static front-end + stateless backend | Vue 2.7 |
| **sub-converter forks / yonggekkk** | — | **Default credentials shipped in README** — never reproduce |

---

## 10. Legal / licensing constraints

- Sub-Store is **AGPL-3.0**, V2RayAggregator **GPL-3.0**, sublink-clash **CC BY-NC 4.0** (non-commercial only) — unusable for anything commercial; read for architecture only.
- Usable options: **sub-web (MIT)**, **sublink-worker (MIT)**, VPNpool's approach (check licensing per file).
- Prefer to **write our own parser/renderer** — the IR and render are the parts we need to differ on anyway (geo/country scoring, RU protocols).
- Cloudflare ToS: don't serve large base64 blobs through a proxied zone's cache; static/R2 path only.
- Never ship default credentials; generate secrets at deploy time.
- **Recommend `docs/LEGAL.md`** stating: nodes are unverified third-party infrastructure, the hub does not relay or log user traffic, users assume risk, and no illegal use.

---

## 11. What the operator's server can actually run [estimate]

- Prober: single long-lived sing-box process with N outbounds + N tagged SOCKS inbounds, driven by Python/asyncio. ~67 MB RSS total (single process) vs ~67 MB × C for subprocess-per-node. **Single-process model chosen.**
- Concurrency: 100 for HTTP-over-proxy, 20 for speed tests, 200 for TCP screen — all far below the empirically safe ceiling of 500, and all socket-bound not CPU-bound (0.4 s CPU for 10k configs).
- Storage: NDJSON event log + SQLite for indexed state. Prom-quality metrics via a `/metrics` endpoint.
- Delivery: nginx serving immutable generated files.
