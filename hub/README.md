# hub — a decentralised FREE VPN platform

A control plane that indexes publicly published proxy configurations, verifies
them, scores them, and republishes them as ordinary client subscriptions. It
never relays user traffic — the server consumes these nodes exactly as an end
user's device would, in order to find out which ones work.

**FREE** reads three ways, and all three hold:

* **free of charge** — there is no paid tier, no quota, no upsell;
* **free as in libres** — a payload is a plain list of public URIs that any
  client can read and anyone can re-host;
* **free as in unblocked** — the point of the product is *access*: a
  subscription that works through RKN filtering.

```
                       ┌────────────────────────────────┐
   systemd timer 15'   │  fetch → parse → probe → score  │
   (or `hub run`)      │          ↓                      │
                       │      tier → render → validate   │
                       └───────────────┬────────────────┘
                                       │ content-addressed generation
                                       ▼
   GET /sub/{token} ──► data/gen-current/verified-sing-box.singbox
   GET /sub/{token}/country/{cc} ──► .../verified-{CC}.singbox
```

## Per-country subscriptions

`/sub/{token}/country/{cc}` serves one country's slice of the `verified` tier.
It exists because the pool is grouped by *measured* exit country (from
`cdn-cgi/trace`, not from the label on a share URI), and a client that only
wants a Dutch exit should not have to page through the whole pool to find one.

```
/sub/{token}/country/nl              # the NL shard, sing-box dialect
/sub/{token}/country/NL              # same link; the segment is case-insensitive
/sub/{token}/country/nl?format=base64  # the same shard as a base64 URI list
```

Only the dialects a core can actually read get a file: shards are written as
`.singbox` and `.base64`, so `?format=clash` on a country link 404s rather than
returning a 200 whose body the client cannot parse. Ask for Clash on the whole
tier (`/sub/{token}?format=clash`), which does have that file.

A country with no shard yet returns 404 **naming the countries that do exist**,
which is the answer a client needs in order to stop retrying:

```json
{"error": "no payload for this country", "country": "FR",
 "countries": ["AT", "DE", "NL", "PL"], "available": ["...", "..."]}
```

Three properties are deliberate:

* **A shard is a subset, never the tier.** With one country in the pool the
  shard legitimately equals the tier; everywhere else it is strictly smaller,
  and the counts in `manifest.json` sum to the tier's count minus the countries
  that fell below the two-node minimum.
* **The name is the API.** `verified-NL.singbox` — the dot between the country
  and the format is what keeps it from reading as `verified-<core>.singbox`. A
  country code is two letters, a core is never two letters; the dot makes the
  split structural instead of a guess. Clients cache these by URL.
* **The guard is the only thing that can 404 a bad code.** `..` matches no
  filename, so a lookup miss would 404 anyway — which is exactly why the test
  writes a file the traversal *does* resolve to. Otherwise deleting the
  validation is invisible to the suite.

Every measured country gets a shard, including a one-node country. The
threshold was 2, reasoning that a one-node file is "a redirect with extra
steps" — that optimises for file count and misses what the endpoint is for: a
user tests *that country*, and a 404 because the country is small is not a
saving, it is the feature being unavailable. The pool is long-tailed, so most
countries have one or two nodes.

## How a visitor picks a country

The landing page renders one card per measured country, sorted deepest-first,
and a card has to lead somewhere. It does not lead to `/sub/{token}` — the page
holds no token and must not: a token baked into a public HTML file is a token
published to the internet, and `/api/v1/stats` publishes counts only by design.

So the chain is:

```
country card ──► https://t.me/{bot}?start=CC ──► bot gates membership,
                                                mints a token, answers with
                                                /sub/{token}/country/CC
```

Enable it by setting `bot_username` in `config/sources.yaml` (without the `@`)
and restarting. Unset — the shipped default — means the cards render as plain
unlinked `<div>`s and nothing points at a bot that does not exist. That
degradation is the honest state for a fresh install; a card that links nowhere
is worse than a card that does not claim to.

What makes this the Marzban shape — *one link, pasted into a client, showing a
list of countries* — is the payload, not the page: every generation carries
`g-{CC}` `urltest` groups per country plus a `proxy` selector over them, so a
client that imported the tier shows one destination per country and rotates
within it. The per-country link narrows that to a single exit; it does not
replace the tier.

## What it is

* an **availability monitor** for public proxy endpoints, with history;
* a **normaliser**: dozens of source formats → one IR → three client dialects;
* a **filter** that runs the checks the incumbent aggregators skip, most
  importantly a *verifying* TLS handshake (a MITM node fails it) and an
  SSRF guard (a poisoned entry pointing at RFC1918 never gets dialled).

## Why it is decentralised

| Property | Mechanism |
|---|---|
| No provider to block | The hub owns no nodes. There is no `vpn.example.com` for a censor to null-route — the endpoints are third-party. |
| No source of truth | Many independent upstreams; any one can vanish without affecting the pool. |
| No artefact to trust blindly | Generations are content-addressed (`gen-<sha256[:12]>`), so the same pool always yields the same id. |
| No single point of failure on deploy | Rollback is a pointer flip. Any retained generation can be served instantly. |
| No lock-in | A payload is a text file: export it, import it elsewhere. |

The index itself is still one server and one vantage point. Mirror
replication, signing, and multi-vantage verification are a sequenced roadmap in
the spec (§12) — the honest claim today is *content-addressed, mirrorable, and
owner-free at the node layer*, not "censorship-proof".

## What it is not

* **not a VPN server**. It owns no nodes and carries no traffic. It is the
  index that makes a free VPN *usable* — the VPN is the set of nodes it lists.
* **not a vouch for the nodes.** Every published node is unverified third-party
  infrastructure operated by unknown parties. A meaningful fraction of free
  proxy endpoints inject content or intercept TLS. Published research on free
  proxy pools found ~4% performing TLS interception and ~16% modifying content.
* **not safe for sensitive use.** Never send credentials, sessions, OTPs, or
  wallet operations through any listed node. Read `docs/LEGAL.md`.

## Network safety — read before running anything

This server is shared working infrastructure. **The VPN hub must not alter the
host's live routing or DNS and must not tunnel ordinary server traffic.** Do not
bind prober listeners to routable interfaces or run probes in the host namespace.
The one deliberate exception is the existing, narrowly scoped `hubns` namespace
uplink created by `deploy/hubns-ensure.sh`; do not change its veth/NAT/firewall
rules. Probe traffic in that namespace is still outbound egress and must not be
started, enabled, or accelerated without explicit authorization.

* Unit tests use scripted `CoreDriver` fakes and do not verify external nodes.
  `tests/test_singbox.py` uses loopback sockets against local fixtures; the real
  binary is only used with `sing-box check` (pure config validation, no outbound).
  Do not interpret the suite as a check of VPN reachability or Happ compatibility.
* Real-node runs happen inside a **named network namespace with an uplink** —
  `hubns` on this host, entered with `ip netns exec hubns`. Not `unshare -rn`,
  and not `PrivateNetwork=yes`: both of those create a namespace with loopback
  and no route out, which sounds like isolation and is actually a disconnection.
  A prober run inside one completes normally and verifies 0 nodes, forever,
  while reporting success — the worst shape of failure, because it is green.
  Outbound to third-party nodes requires the explicit operator opt-in
  (`hub run --allow-network`) *and* a gate check that the isolation is real, and
  the gate now accepts exactly two answers: *only* `lo` is visible (via
  `/proc/net/dev`, which is per-netns), or this is a named namespace in
  `/run/netns` (matched by inode, because those bind mounts *are* the namespace
  inode and are readable unprivileged). Anything else is refused with the
  reason. "Can isolate if someone bothered" used to be a third accepted answer,
  and it green-lit the host.
* `hub-probe.service` enforces the same isolation inside the unit itself:
  `ip netns exec hubns` on the ExecStart line, `setpriv` to drop back from root
  to the unprivileged user after entering, and `Nice`/`IOSchedulingClass=idle`
  so a four-times-a-day probe never starves the other projects on the box.
  `hub-ns.service` recreates `hubns` at boot. See the header of
  `deploy/hub-probe.service` for the two mechanisms that were tried, measured,
  and rejected, and the exact commands that build the namespace.

Before and after any network-touching run, `ip route` and `ss -ltn` on the host
must be unchanged — and the stronger, checkable version of that: no `sing-box`
listener may be visible from the host namespace at all. They are bound to
`127.0.0.1` *inside* `hubns`, so `ss -tlnp | grep sing-box` from the host is
empty while hundreds of them are running. That was verified during a live run:
771 children, 0 visible.

* A node that fails to *start* is now an error, not a dead port.
  `SingBoxDriver.add_node` used to wait for its child to listen, give up
  silently, and return success — leaving an entry in `driver.entries` whose port
  nothing was bound to. `speed_read`'s only guard is that entry, so a stale one
  turned "this config did not start" into `ConnectionRefusedError` on
  `127.0.0.1`: the same error a genuinely dead node produces, which means the
  funnel read the driver's own failure as a fact about the node. Found on this
  box with a live run — 12 of 12 `add_node` calls returned without raising, and
  one node was already unreachable. Both silent paths (child exited, deadline
  expired) now raise `SingBoxStartError`, and the half-written entry is removed
  before the raise. Two tests, one per path, because the first path's test
  cannot reach the second: `--die` exits before the first poll iteration, so it
  short-circuits on `returncode` and never arrives at the deadline.

* The speed stage now asks the right question. `speed.measured: 0` stood in
  every round recorded on this host, and `HUB_MAX_LOAD`'s unreachable per-core
  ceiling was the visible explanation — which hid **four** independent causes
  behind one plausible one. Three are fixed: the `dedup_key`→`node_tag`
  translation, the ceiling (`HUB_MAX_LOAD=none HUB_TOP_N=25` on the unit's
  ExecStart), and `speed_read` reading the response head with a helper that
  waits for EOF, so a live-but-slow node handed the consumer nothing until the
  connection closed (`_read_head` now stops at the header terminator).
* The fourth was the one that mattered, and it is worth stating plainly because
  two docstrings here first got it wrong. `_split_url` returned
  `urlsplit(url).path`, which **never contains the query string**, so a request
  for `https://speed.cloudflare.com/__down?bytes=262144` went out as
  `GET /__down` with the size parameter silently gone. Cloudflare's endpoint
  takes its response size only from `?bytes=`, so the driver asked for a bounded
  transfer, sent an unbounded one, and measured nothing. How it survived a green
  suite: the four `_split_url` cases were all query-free, and the speed test
  asserted `b"GET /__down" in request` — and `/__down` is a *substring* of
  `/__down?bytes=4096`, so that check passed with the query dropped. Both are
  fixed: the parametrization now includes query-bearing URLs, and the speed test
  pins the whole request line (`GET /__down?bytes=4096 HTTP/1.1`).
* The discipline that caught it: after the `_read_head` fix I re-ran the live
  probe instead of trusting the reasoning. `run-20261015T215128Z` came back
  `170 verified → 65 published` with `speed.measured: 0` and
  `speed.fail:no bytes: 25` — the top-N cap, every attempted node, in a run whose
  HTTP stage had just verified 170 nodes through the same SOCKS plumbing. A fix
  that is confirmed by a *live* measurement is the only kind this project
  accepts; the run is what told the two causes apart.

## Status

Working MVP. The five pipeline stages, the `sing-box` `CoreDriver`, three
renderers, the gate, and the CLI are implemented and unit-tested. The driver
needs the binary present; everything else runs offline. Probing needs the
binary *and* a usable network namespace, which is why `hub run` still reports
`0 verified` on a box with neither — honestly, naming the reason.

Unit suite: `python -m pytest tests/`. The renderer and pipeline can be exercised
hermetically with injected validators; production publication requires local
format-specific validation, including `sing-box check`. `tests/test_imports.py`
imports every module in a fresh interpreter, which keeps optional FastAPI/aiogram
imports from breaking the parser and renderer.

## Layout

```
src/hub/
  parser.py     share URI → Node  (vless/vmess/trojan/ss/hysteria2/tuic/wg/socks)
  prober.py     5-stage funnel + SSRF guard; talks to a CoreDriver protocol
  scorer.py     0–100 rubric, versioned, per-factor breakdown published
  renderer.py   3 formats (base64 / sing-box JSON / Clash YAML) × 3 cores
  tiers.py      curated(30) / verified(150), per-source caps, anti-Sybil
  fetcher.py    raw GitHub + jsDelivr, ETag-conditional, no REST API
  store.py      SQLite index + NDJSON fact log + immutable generations
  pipeline.py   orchestration, fail-open, atomic pointer flip
  api.py        FastAPI: /sub/{token}, /sub/{token}/country/{cc}, /, /static/*,
                /healthz, /metrics
  ui/           landing page: index.html + hub.css + hub.js (no dependencies)
  bot.py        aiogram 3.x long-poll, MockTransport, deep links
  gate.py       membership cache + invalidation
  cli.py        python -m hub serve|run|rollback|stats|check-parser|bot|init
config/         sources.yaml and scoring.yaml, both versioned
deploy/         systemd units + nginx.conf + run-external.sh
docs/           research, design spec, LEGAL.md
make_demo_generation.py   offline demo pool for exercising the API end to end
requirements.txt          runtime + dev floors
```

## The naming rule, in one line

`pipeline._publish` writes `{tier}-{core}.{fmt}` (e.g. `verified-sing-box.singbox`)
and `api._payload_path` reads exactly that. Those two functions are the only
places in the codebase that know the scheme, and `tests/test_api.py` creates
fixture files with the producer's spelling so a drift between them fails a test
instead of a user's import.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'          # fastapi, uvicorn, aiogram, pytest
# Optional tools (see below for what expands)
mkdir -p tools && curl -sSL -o tools/sb.tar.gz \
  "https://github.com/SagerNet/sing-box/releases/download/v1.12.14/sing-box-1.12.14-linux-amd64.tar.gz" \
  && tar xzf tools/sb.tar.gz -C tools
```

`sing-box` is used for two things: `sing-box check` to validate a candidate
config before it is published, and a single long-lived process holding N
outbounds + N tagged SOCKS inbounds so the HTTP stage can dial each node
without spawning a process per node. It is not vendored; download it.

## Run

```bash
PYTHONPATH=src python -m hub.cli run         # one pipeline run; writes data/gen-*/ and flips the pointer
PYTHONPATH=src python -m hub.cli serve       # FastAPI on 127.0.0.1:8090
PYTHONPATH=src python -m hub.cli stats       # pool health, live generation, published tiers
PYTHONPATH=src python -m hub.cli rollback    # repoint to the retained previous generation
PYTHONPATH=src python -m hub.cli verify-log  # replay the NDJSON event log
```

`PYTHONPATH=src` is not optional decoration: `python -m hub.cli` resolves
`hub` only from an installed package or from `PYTHONPATH`, so without it the
process dies with `No module named 'hub'` — an error that looks, from the
outside, exactly like a broken application.

`hub run` works without any network: sources that fail are skipped, and a run
with no verified nodes leaves the previous generation live (fail-open).

`hub serve` needs one environment variable:

```bash
export HUB_TOKEN=somerandomstring   # the operator token; also usable as /sub/{token}
```

For local development, `hub serve` binds to `127.0.0.1:8090` by default. On this
host that default is the production bind too: `hub-api.service` runs `hub serve`
with `HUB_HOST=127.0.0.1`, and nginx on `:8444` is the only public path. The
`deploy/run-external.sh` and `hub-api-external.service` files are legacy/demo-only
and must not be used in production: the API must stay loopback-bound behind the
hub-specific TLS nginx vhost.

## The landing page

`GET /` is a real page, not a status message: `src/hub/ui/index.html` styled by
`hub.css`, with the pool section rendered client-side from `/api/v1/stats`. Two
constraints shape it:

* **no external requests** — no font, no CDN, no analytics. A landing page that
  fetches a webfont leaks every visitor's IP to a third party, which is the same
  reason the hub relays no traffic at all;
* **aggregates only** — `/api/v1/stats` returns counts by protocol and score
  band, never a node row. A public node list is a ready-made blocklist, so the
  per-node data stays behind `/sub/{token}`.

`curl` cannot verify this page: the pool section is empty in the raw HTML
*because* JavaScript fills it. Assert the render by running `hub.js` against the
real payload in a JS runtime — that is the only way a mistyped field shows up as
a blank section instead of a green test.


## Design decisions worth knowing

**`sing-box check` gates every payload.** A payload that does not validate is
discarded, not published. The previous generation stays live. An empty
subscription is prohibited; a stale one is only bad.

**Immutable generations with a content-derived id.** Same pool in the same
order produces the same `gen-<sha>`, so re-runs are naturally idempotent and
rollback is a pointer move. Three generations are retained.

**Tags are minted server-side.** Duplicate outbound tags are a hard `FATAL` in
sing-box and an illegal config in mihomo, so we never reuse a source's remark.

**`interval` differs by format.** `"10m"` (Go duration) for sing-box, `600`
(int seconds) for Clash. One model, two renderers.

**`client_core` is a render parameter.** Upstream sing-box does not implement
XHTTP; an XHTTP payload shipped as sing-box-compatible is dead on arrival.
Hysteria2 conversely needs sing-box/mihomo, so it is dropped for Xray-only.

**Fails closed on nodes, fails open on the service.** A node that cannot be
validated is dropped; the service never stops serving because of it.

**Concurrency is socket-bound, not CPU-bound.** v2go measures ~40 µs of CPU per
config, so 10k configs cost 0.4 s. The limits (200 TCP, 100 HTTP, 20 speed)
exist because the *targets* degrade above them, not because we cannot afford
more.

### How speed is measured, and what it costs

There are two cases and they must not be confused:

* **OpenVPN / SoftEther over VPN Gate.** VPN Gate publishes `Ping` and `Speed`
  (bytes/second) per server, measured upstream. Ranking those is a *sort* over
  data the source already measured, at the cost of one HTTP GET. `hub
  speedtest` does exactly that, and `_rank_by_source_numbers` never transfers a
  byte. Treating a source's claim as our own measurement is how a ranking ends
  up certifying nodes nobody ever connected to.
* **Share-URI nodes (VLESS / Trojan / VMess / Hysteria2).** There is no source
  number here, so the number is *measured*: `hub.speedtest` registers the node
  with the driver and reads through that node's own SOCKS port from Cloudflare's
  throttled `__down?bytes=` endpoint — which is served from the *node's exit*,
  not from ours.

The measurement is bounded on three axes, all of them load-bearing:

| Bound | Value | Why |
| --- | --- | --- |
| Bytes per node | 256 KiB probe → 4 MiB max | a dead-slow node costs a quarter megabyte, not four |
| Window per node | 12 s, closes early at 1 MiB | a fast link finishes in 0.2 s; timing the full 4 MiB teaches nothing new |
| Pool per round | `top_n=150` | total ≤ 600 MiB, and only *from the node's exit* — the host's uplink is never the source of these bytes |

Six hundred MiB is not free, which is why the round is capped and why the
deferral map exists: a round that skipped nodes because the host was busy has
to *say so*, or "the pool looks small" is indistinguishable from "there were
only 20 fast nodes".

### Two knobs that decide whether the speed stage runs at all

Both are read from the environment by `hub.cli`, so a unit file or a shell can
set them without a code change:

| Variable | Default | Effect |
| --- | --- | --- |
| `HUB_MAX_LOAD` | `0.85` | Refuse to start a measurement round when per-core load is at or above this. `none`/`off` disables the check. |
| `HUB_TOP_N` | `150` | How many nodes to measure per round, best-ranked first. |

They exist because of a measured fact about this box: an 0.85 **per-core**
ceiling is correct for a dedicated host and *unreachable* on one running an
operator desktop, a browser and a VM. At a sustained 1.5–2.5 load per core,
every round deferred forever — `speed.measured` stayed 0 in every single run,
the ranking was scored entirely on half-credit throughput, and the feature was
effectively off. A guard that can never be satisfied is a guard that has become
a false claim about the system.

So the ceiling is a knob rather than a constant, and **lifting it is a
deliberate trade**: the throughput number then measures the co-tenant as much
as the node, so it is worse as a ranking signal, not better. Reading a
throughput figure off a saturated box means believing that figure.

A second, separate cause of `speed.measured: 0` was found and fixed in the same
investigation, which is worth recording because the two looked identical from
the outside. `SpeedStage` was handing the driver full 64-char `dedup_key`s where
the driver registers and looks up by the **16-char** `node_tag`, so every lookup
missed and every transfer read an empty stream — the load guard was a visible
explanation for a symptom it did not cause. The run report now separates them:
`speed.measured` and `speed.defer:*` are the pool's story, and
`speed.fail:<reason>` is the box's — a round where every transfer failed is no
longer reported as a round that merely found nothing fast.

Ranking breaks the obvious circularity — which nodes are worth a megabyte each
is the question the score answers, but the score needs speed — by scoring an
unmeasured node at **half credit** rather than zero. A provisional ranking
therefore exists before any bytes move; the top of it is measured, and the
measurements are fed back in before the pool is published. A node nobody had
time to measure keeps its half credit and is visibly not a measured zero.

**A verifying TLS handshake is the differentiator.** The incumbent aggregators
check reachability; a MITM endpoint answers reachability fine. `_tls_inner`
builds a real verifying context and marks a node `cert_substituted` when the
chain is untrusted or the name does not match.

## Deploy

Eight systemd units, one unprivileged user, no Docker:

```
hub-worker.service   oneshot: hub run            (never --allow-network)
hub-worker.timer     OnCalendar=*:0/15, Persistent=true
hub-probe.service    oneshot: hub run --allow-network, inside `ip netns exec hubns`
hub-probe.timer      OnCalendar=00/6:17, Persistent=true   <-- the re-check
hub-ns.service       recreates `hubns` at boot (tmpfs, so a reboot deletes it)
hub-api.service      ExecStart=hub serve --host 127.0.0.1 --port 8090
hub-api-external.service  legacy/demo only; do not enable in production
hub-bot.service      optional; needs TELEGRAM_BOT_TOKEN
```

`Persistent=true` on both timers is what makes the dead-man's-switch real: a
missed run catches up on boot instead of silently skipping — the failure mode
of the GitHub Actions approach (schedules disable after 60 days of repo
inactivity, with no notification).

### The two cadences, and why they are separate

`hub-worker.timer` refetches the public source lists every 15 minutes. That
unit has no `--allow-network`, so it never constructs the sing-box driver and
never opens a probe socket. What it can do with that refetch is bounded and
worth stating exactly, because the obvious reading is wrong: without a driver
it verifies **0** nodes, so it publishes **nothing** and keeps the previous
generation untouched. Its observable output is therefore the fetch diagnostics
and per-source health in `data/events.ndjson`, not a fresh subscription. The
journal for a run says so literally — `0 verified -> 0 published (kept
previous)`. Only `hub-probe.service`, the unit that would have to run the
prober, can produce a new generation by running with `--allow-network` inside
`hubns`.

Those two timers are deliberately **not** merged into one, but the split does
not yet earn its cost: the 15-minute refetch runs 96 times a day to record
source health while the pool that clients actually receive changes only on the
6-hour probe. If the fetch diagnostics are not being watched, the refetch
interval is a candidate to widen until it is — the probe cadence is what the
freshness promise depends on, and it is the expensive half.

`hub-probe.timer` is the periodic re-check the project was asked for: four times
a day at 17 minutes past 00/06/12/18. It drives the one unit that probes nodes,
and that unit's isolation is a **named network namespace, `hubns`, entered with
`ip netns exec`** — not `PrivateNetwork=yes`.

That distinction is the difference between a sandbox and a disconnection, and
both wrong answers were tried first and measured:

| Mechanism | What actually happened | Verified |
| --- | --- | --- |
| `PrivateNetwork=yes` | systemd hands the unit a netns with no external interface and no default route. Nothing can be dialled, so the run completes and verifies **0 nodes, forever, while reporting success** | yes |
| `unshare -rnf --map-user=` | a fresh netns contains `lo` and nothing else — `[(1,'lo')]` versus the host's `[(1,'lo'),(2,'eth0'),(3,'docker0'),(6,'veth-hub-br')]`. A second failure masks the first: a single-uid namespace maps one id, so `/home/dev` appears `65534:65534` and the run dies on `PermissionError` | yes |
| `ip netns exec hubns` | loopback is *per network namespace*, so the driver's per-node SOCKS listener is unreachable from the host **by construction** — the address resolves to a different device, not by a permission bit | yes |

`hubns` is a veth pair: `veth-hub 10.99.0.2/24` inside, `veth-hub-br 10.99.0.1/24`
outside, `ip_forward=1`, and one `MASQUERADE` for `10.99.0.0/24`. The rule that
generalises is **isolation must sandbox, not disconnect**: a prober needs its own
uplink. `hub-probe.service`'s header records the whole excavation, including the
`FORWARD` policy-DROP rules that a NAT rule alone does not cover — without them a
namespace exists, dials a node, and reports it dead.

`hubns` lives on `/run/netns`, which is tmpfs, so **a reboot deletes it** and
`hub-ns.service` + `deploy/hubns-ensure.sh` recreate it at boot. That unit is not
a nicety: `hub-probe.timer` is `Persistent=true`, so a missed round fires on
boot — i.e. the dead-man's-switch aims the prober at the one moment its sandbox
provably does not exist.

The two are deliberately not merged. The refetch is cheap enough to want fresh
and does not need the driver; the probe is expensive (one TCP/TLS/HTTP round
per node, then a bounded transfer for the top `top_n`) and answers a different
question. Coupling them would force one number to serve both, and the natural
choice — "as often as the refetch" — is exactly the wrong one for the probe.

Enabling the re-check is opt-in by design:

```
sudo systemctl enable --now hub-probe.timer   # and nothing else
```

`hub-probe.service` has an empty `[Install]` section: `systemctl enable` of the
service alone must **not** pull probing into boot.

The worker must run as a user who can write `data/` and nothing else. The API
must not be exposed directly — put nginx in front with TLS and a
`X-Forwarded-For` header, and firewall the port.

### IP-only test endpoint and TLS status

The hub origin is `https://<host>:8444`; port 443 belongs to other nginx
sites, and 8443 is used by the neighboring Marzban deployment. The API binds
only to `127.0.0.1:8090`; the hub-specific nginx vhost is the only public path.

**This endpoint now terminates a publicly trusted certificate.** It is a
Let's Encrypt certificate for the bare IP, from the `shortlived` profile
(~160 h), in its own lineage — named after the address it is issued for, e.g.
`hub-ip-203-0-113-10` — under `/etc/letsencrypt`.
Its SAN is a `critical` `IP Address:` extension — the profile that
carries it is the only one Let's Encrypt offers for IP identifiers, so
short-lived and separately renewed is inherent, not a choice. Ordinary chain
validation succeeds: `curl https://<host>:8444/healthz` returns 200
without `-k`. A client importing the subscription does verify the chain and
needs no bypass.

Renewal is the pre-existing `certbot-le.timer` (03:00 and 15:00 daily) with its
`certbot-le-nginx-reload` deploy hook, which runs `nginx -t` and reloads only on
success. That timer already renews the default `/etc/letsencrypt` config
directory, so this lineage is picked up without new units. Certbot 5.4+ is
required for `--ip-address`; the box runs 5.7 in `/opt/certbot-le`, separate
from the distro's certbot 2.9 that serves the domain lineages.

Freshness is not the same as trust. The certificate is valid for days, but the
published node pool is only as new as the last probe round (every 6 hours at 17
minutes past). `/healthz` reports `stale` after seven hours — one probe cycle
plus slack, so `stale` means a scheduled round did not happen rather than "the
last round was a while ago, as planned". An install that probes on another
cadence sets `HUB_STALE_AFTER_HOURS` in `/etc/hub/hub.env` to match it. Check
the generation timestamp before concluding a subscription is current.

The configured `base_url` supplies the origin for API response headers and links.
Its presence is not evidence that the endpoint is reachable or TLS-trusted.

## Anti-abuse posture

The token gates *who can issue a subscription identity*, not *what is in the
list* — the list derives from public sources. That is a deliberate decision:
a bearer-token scheme protects a secret, and there is no secret here. What the
token does protect against is unauthenticated polling. Both a per-token and a
per-subnet bucket are enforced, and enumers get a 404 rather than a 401 so a
scanner cannot distinguish "exists" from "does not".

## Testing

```bash
python3 run_tests.py          # pytest wrapper; prints the paths it adds
python3 -m pytest tests/ -q   # equivalent, if pytest is already importable
```

The suite is hermetic by construction: **no test opens a socket.** The prober's
two network stages — the stage-1 TCP dial and the stage-2 verifying TLS
handshake — are injected as no-ops in `tests/test_prober.py`, and the pipeline
tests collapse the same seams via `_offline()`. This is why the suite is safe to
run on the live server: it cannot touch the host network, change a route, or bind
a routable listener, no matter what a future contributor writes into a driver.

`tests/test_imports.py` additionally imports every module in a fresh
interpreter, which is what keeps the stdlib-only property honest (the pipeline,
parser, and renderer run on a box with no FastAPI or aiogram installed).

Real-node probing is not covered by this suite on purpose. It needs the
`sing-box` binary and the isolation described under *Network safety* above —
its shape is documented in `deploy/hub-probe.service`, not in a test.

## Further reading

* `docs/superpowers/specs/2026-10-14-subscription-hub-research.md` — verified
  findings that constrain the design, each with a primary source.
* `docs/superpowers/specs/2026-10-14-subscription-hub-protocols-clients.md` —
  protocol landscape for RU/СНГ, client matrix, and the traps that break naive
  generators.
* `docs/superpowers/specs/2026-10-14-subscription-hub-design.md` — the design
  spec: architecture, payload tiers, failure posture, open decisions.
* `docs/LEGAL.md` — what this project is and is not, and the warnings users
  must read before use.

## Licence

AGPL-3.0-or-later — see `LICENSE`.

Chosen for what this software is rather than by habit. The value here is the
verification pipeline, and the AGPL is the licence that keeps a hosted fork's
improvements public: run a modified copy as a network service and you must
publish your changes. Marzban, the closest project in this space, made the same
call. If you need different terms, open an issue rather than forking silently.

The licence covers **the code**. It says nothing about the nodes, which are
third-party public infrastructure either way.

Node credentials in `data/` are third-party public data; treat the directory as
non-public and never commit it.
