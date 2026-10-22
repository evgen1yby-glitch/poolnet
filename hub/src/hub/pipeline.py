"""The pipeline. fetch -> parse -> probe -> score -> tier -> render -> publish.

Invariants enforced here, because callers cannot enforce them:

1. **A generation is immutable.** Its directory is written to a temp name and
   renamed into place, so a half-written payload is never addressable.
2. **A payload is never published unvalidated.** Every candidate goes through
   `sing-box check`; a payload that fails is discarded and the previous one
   stays live.
3. **Pointer flips are atomic.** `os.replace` on a small JSON file, so a reader
   sees the old pointer or the new one, never a torn path.
4. **Fail-open.** Any stage that fails keeps the previous generation. The only
   non-recoverable failure is "no generation has ever been published", which is
   a first-run problem, not an incident.
5. **Node-count drift is bounded.** A run whose verified pool shrinks by more
   than 40% vs the last generation is published with a warning but not blocked —
   a source outage is a real event, and an empty subscription is worse than a
   small one.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import adapters, fetcher, parser as uri_parser, tiers as tierlib
from .gate import RateLimiter
from .models import Format, Node, ProbeResult, Stage, Tier, is_blocked_address
from .prober import Concurrency, CoreDriver, Prober
from .renderer import RenderParams, country_shards, render_validated
from .scorer import History, Weights, score as score_node
from .speedtest import SpeedPolicy, SpeedReport, SpeedStage, apply_speed
from .store import Store
from .store_state import node_to_json


_publish_lock_guard = threading.Lock()


@contextmanager
def _publish_lock(path: Path):
    """Serialize publishers across threads and processes for one Store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _publish_lock_guard:
        with path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

#: A run producing fewer than this many verified nodes is reported as a
#: degraded run rather than a failure.
MIN_USABLE_POOL = 10


def _host_load() -> float:
    """Load average per core, or 0.0 when the value cannot be read.

    Per core, not absolute: `/proc/loadavg` on a 4-core box at load 8 is
    saturated, while on a 12-core box at load 8 it is two-thirds idle. An
    absolute threshold therefore means different things on every machine, and
    on this one — 12 cores and a co-tenant VPN project — the conservative
    absolute default of 4.0 would defer *every* round for the lifetime of the
    process. Normalising at the reader rather than at the threshold moves the
    same knob to a per-core scale, where 1.0 means "one runnable task per
    core" and the number is comparable across hosts.

    Injected into the speed stage rather than imported by it: `speedtest` has
    no business knowing this file's host, and the guard stays testable by
    passing a different callable.
    """
    try:
        with open("/proc/loadavg", encoding="utf-8") as handle:
            load = float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0
    cores = os.cpu_count() or 1
    return load / cores



def _default_geo_lookup(addresses, *, now=""):
    """The production geo resolver, owned by the pipeline module.

    Built here rather than in `cli.py` so the CLI only has to say "on", and
    wrapped so the cache lives beside the store it belongs to rather than in
    module state shared by every `Pipeline` in a process — two stores in one
    process must not share a geo cache.
    """
    from .geo import GeoCache, lookup_countries

    cache = GeoCache(_GEO_DB_PATH)
    try:
        return lookup_countries(list(addresses), cache=cache, now=now)
    finally:
        cache.close()


#: Resolved lazily so importing the pipeline does not depend on a Store.
_GEO_DB_PATH = Path(os.environ.get("HUB_ROOT", ".")) / "data" / "hub.db"

def _reason_counts(deferred: dict[str, str]) -> dict[str, int]:
    """Collapse a per-node reason map to `reason -> count`.

    The reasons are per-node strings with numbers in them ("beyond top_n=150",
    "host load 7.31 >= 4.0"), so counting them verbatim would produce one key per
    node and report nothing. The rule is: **everything up to the first digit is
    the category, and the rest is what varies.**

    What that rule does to a failure reason, stated plainly, because it is easy
    to over-claim and the over-claim is worse than the truncation:

        "OSError: socks connect failed: code 1"   ->  "OSError: socks connect failed: code"
        "ConnectionRefusedError: [Errno 111] ..." -> "ConnectionRefusedError: [Errno"

    A fragment, not a sentence, and the number — which is the first thing an
    operator would reach for — is gone. That is a real cost, paid deliberately:
    the alternative (keeping digits that are part of a reason's own name) needs
    a rule about which digits vary and which do not, and on this codebase's
    actual reason strings **the fancy rule produced byte-identical output to
    this one**. So the complexity bought nothing and was removed rather than
    left in place looking like it did something.

    What survives truncation is the part that matters: the distinct families
    stay distinct. `OSError: ... code` (the node refused the SOCKS dial) and
    `ConnectionRefusedError: [Errno` (our own listener was never there) are two
    different causes and remain two different keys, which is the whole point of
    bucketing rather than dropping the reason. Per-node detail is the job of the
    event log, not of a count.
    """
    counts: dict[str, int] = {}
    for reason in deferred.values():
        # Everything from the first digit onward is the value that varies
        # ("beyond top_n=150", "host load 7.31 >= 4.0"); what precedes it is
        # the stable prefix ("beyond top_n", "host load"). Trailing punctuation
        # is stripped so the bucket reads as a name rather than a fragment.
        head = ""
        for char in reason:
            if char.isdigit():
                break
            head += char
        bucket = head.strip().rstrip("=:<").strip() or "unknown"
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _result_for(results: Sequence[ProbeResult], node: Node) -> ProbeResult:
    """The `ProbeResult` for `node`, or a failed placeholder.

    An empty placeholder rather than `None`: `score_node` dereferences the
    probe unconditionally, and a survivor whose result is missing from the list
    should be scored as a bad node rather than crash the run after the network
    work is already done.
    """
    for result in results:
        if result.dedup_key == node.dedup_key:
            return result
    return ProbeResult(node.dedup_key, Stage.TCP, ok=False, error="no result")


@dataclass
class RunReport:
    run_id: str
    started_at: str
    finished_at: str = ""
    nodes_raw: int = 0
    nodes_parsed: int = 0
    parse_errors: int = 0
    nodes_verified: int = 0
    published: int = 0
    generation: str = ""
    sha256: str = ""
    fatal: bool = False
    fatal_reason: str = ""
    stage_survivors: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    tier_counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _published_counts(payloads: Sequence[tuple[str, str, bytes, int, str, str]]):
    """`(published, tier_counts)` for the payload rows that were written.

    Both numbers are counts of **nodes**, not of payload-node products, and
    that distinction is the whole point. One pool is written as ~15 payloads
    (3 cores x 3 formats + one file per country), each carrying the same nodes
    again, so summing the per-payload counts reports 335 for a 39-node pool —
    a number that matches nothing on disk, and that the drift check then
    compares against the next run's real 39.

    `published` is taken from the whole-tier payloads only (`kind` set), which
    is the set of every node published this run: a shard is a subset of its
    tier, so counting it too would double-count. `tier_counts` is the same
    number resolved once per tier, so a multi-tier run reports both.
    """
    per_tier: dict[str, int] = {}
    for tier, _name, _payload, count, kind, _cc in payloads:
        if kind:
            per_tier[tier] = max(per_tier.get(tier, 0), count)
    total = sum(per_tier.values())
    return total, per_tier


class Pipeline:
    def __init__(
        self,
        root: Path,
        *,
        sources: dict | None = None,
        driver_factory: Optional[Callable[[], CoreDriver]] = None,
        weights: Weights | None = None,
        policies=None,
        validate: Optional[Callable[[str, Format], bool]] = None,
        min_pool: int = MIN_USABLE_POOL,
        concurrency: Concurrency | None = None,
        connect: Optional[Callable] = None,
        handshake: Optional[Callable] = None,
        network: bool = False,
        speed_policy: Optional[SpeedPolicy] = None,
        geo_lookup: Optional[Callable[..., dict[str, str]]] = None,
        recent_hours: int = 0,
    ) -> None:
        self.root = Path(root)
        self.store = Store(self.root)
        self.sources = sources or {}
        self.weights = weights or Weights()
        self.policies = policies or tierlib.DEFAULT_POLICIES
        self._driver_factory = driver_factory
        self._validate = validate
        self.min_pool = min_pool
        #: Probe tuning and the two network seams. Both default to "the real
        #: network"; tests collapse them to no-ops, because a pipeline test
        #: with synthetic `*.example.com` nodes must not dial them.
        self.concurrency = concurrency or Concurrency()
        self._connect = connect
        self._handshake = handshake
        #: Whether this pipeline is allowed to move bytes for a throughput
        #: measurement. Defaults off and is only set by `hub run
        #: --allow-network`: a transfer is the most expensive thing the system
        #: does, and it must be the thing the operator opted into explicitly
        #: rather than a side effect of a driver being present.
        self.network = network
        self.speed_policy = speed_policy or SpeedPolicy()
        #: Injected geo-IP lookup, `(addresses, *, now) -> {address: code}`.
        #:
        #: **Off unless injected.** Defaulting it on would make every existing
        #: test open an HTTP connection to a third party, which is exactly the
        #: property the hermetic suite exists to have; and a country resolver
        #: that runs by default is a new outbound dependency nobody opted into.
        #: Production injects `_default_geo_lookup` from the CLI.
        self.geo_lookup = geo_lookup
        #: Hours of check history that still count as "working". 0 disables the
        #: carry-over, which is what the hermetic tests use: a test that must be
        #: deterministic cannot depend on a wall-clock window.
        self.recent_hours = recent_hours

    # -- helpers ----------------------------------------------------------

    def _source_kinds(self) -> dict[str, str]:
        """`source name -> adapter kind`, for the sources that declare one.

        Read off the source list rather than a separate config key, so a
        source and its adapter cannot drift apart: adding a `kind:` line to
        the YAML is the only place either is named.
        """
        kinds: dict[str, str] = {}
        for entry in self._fetch_sources():
            if entry.kind:
                kinds[entry.key] = entry.kind
        return kinds

    def _fetch_sources(self) -> list[fetcher.Source]:
        raw = self.sources.get("sources", [])
        sources = []
        for entry in raw:
            if isinstance(entry, fetcher.Source):
                sources.append(entry)
            elif isinstance(entry, dict):
                sources.append(fetcher.Source(**entry))
            else:
                sources.append(fetcher.Source(url=str(entry)))
        return [s for s in sources if s.enabled]

    def _source_filters(self, attr: str) -> dict[str, tuple]:
        """`{source name: compiled filters}` for `include` or `exclude`.

        Compiled once per run rather than per line: these are the documented
        per-source line filters, so a body with thousands of lines paid the
        compile cost every line until this.

        A pattern that does not compile **raises**, naming the source, the field
        and the pattern. Swallowing it would look identical to "this source
        declared no filters", which is the opposite of what the operator wrote:
        `include: ['('` means "vless only, and nothing else at all", and
        dropping it would publish every line the filter existed to exclude.
        """
        compiled: dict[str, tuple] = {}
        for entry in self._fetch_sources():
            patterns = tuple(getattr(entry, attr) or ())
            if not patterns:
                continue
            try:
                compiled[entry.key] = tuple(re.compile(p) for p in patterns)
            except re.error as exc:
                raise ValueError(
                    f"source {entry.key!r} has an invalid `{attr}` pattern "
                    f"{patterns!r}: {exc}"
                ) from exc
        return compiled

    @staticmethod
    def _filter_body(
        body: str, include: dict[str, tuple], exclude: dict[str, tuple], key: str
    ) -> str:
        """Apply a source's line filters to its body.

        `include` keeps only matching lines and `exclude` drops matching ones,
        in that order, so `include: ['^vless']` plus `exclude: ['example']`
        means "vless nodes, but not the example ones". Lines the filters reject
        are dropped *before* parsing, which is the documented meaning: the
        generic `parse_many` takes no filter argument, and filtering after
        parsing would have recorded parse errors for lines the operator
        explicitly said to ignore.
        """
        inc = include.get(key) or ()
        exc = exclude.get(key) or ()
        if not inc and not exc:
            return body
        kept = []
        for line in body.splitlines():
            if inc and not any(p.search(line) for p in inc):
                continue
            if exc and any(p.search(line) for p in exc):
                continue
            kept.append(line)
        return "\n".join(kept)

    def _close_round(self, fetcher_instance, source_key: str, nodes: int) -> None:
        """Record a source's round outcome and persist its counters.

        `nodes` is what this round *contributed* to the pool, after filters, the
        SSRF drop and the quarantine cap — so a cap that dropped 900 nodes
        counts as a non-empty round rather than an empty one. That is
        deliberate: quarantine limits how much a new source can add, it does not
        mean the source gave us nothing.

        The URL is the database key, and the name is what the fetcher and the
        config use, so the mapping goes name → URL here.
        """
        entry = next(
            (s for s in self._fetch_sources() if s.key == source_key), None
        )
        if entry is None:
            return
        fetcher_instance.note_yield(entry.url, nodes)
        fetcher_instance.end_round(entry, nodes)
        self.store.save_source_state(
            entry.url,
            etag=fetcher_instance.state(entry.url).get("etag") or "",
            body=fetcher_instance.state(entry.url).get("body") or "",
            rounds=fetcher_instance.state(entry.url).get("rounds") or 0,
            empty_rounds=fetcher_instance.state(entry.url).get("empty_rounds") or 0,
            last_ok=fetcher_instance.state(entry.url).get("last_ok"),
            enabled=fetcher_instance.state(entry.url).get("enabled", 1),
        )

    async def _probe(
        self, nodes: Sequence[Node], driver: "CoreDriver | None" = None
    ) -> tuple[list[ProbeResult], dict]:
        if driver is None:
            # No driver means no network: the pipeline still runs, reports
            # zero verified, and keeps the previous generation. This is the
            # path the CLI takes before sing-box is installed.
            return [], {"driver": "absent"}
        prober = Prober(
            driver=driver,
            concurrency=self.concurrency,
            canary_token=self.sources.get("canary_token", ""),
            connect=self._connect,
            handshake=self._handshake,
        )
        report = await prober.run(nodes)
        stats: dict = {
            **{f"survivors.{k}": v for k, v in report.stage_survivors.items()},
            **{f"errors.{k}": v for k, v in report.stage_errors.items()},
        }
        # `driver_error` is passed through only when there is one, because the
        # happy case is 99% of runs and an empty key in every event is noise. It
        # is the difference between "0 verified, driver failed" and "0 verified,
        # driver failed with `SingBoxUnavailable: sing-box was not found ...`",
        # and only the second is actionable.
        if report.driver_error:
            stats["driver_error"] = report.driver_error
        return report.results, stats

    def _history(self, conn, key: str) -> History:
        row = conn.execute(
            "SELECT COUNT(*) AS rounds, SUM(ok) AS ok FROM checks WHERE dedup_key = ? AND run_at >= datetime('now', '-30 days')",
            (key,),
        ).fetchone()
        rounds = int(row["rounds"] or 0)
        successes = int(row["ok"] or 0)
        # `None` when unmeasured: the scorer then uses its published static
        # table. A measured `0.5` must survive as 0.5.
        first_seen = conn.execute(
            "SELECT MIN(run_at) FROM checks WHERE dedup_key = ? AND run_at >= datetime('now', '-30 days')",
            (key,),
        ).fetchone()[0]
        published_days = 0
        if first_seen:
            try:
                first = datetime.fromisoformat(str(first_seen).replace("Z", "+00:00"))
                if first.tzinfo is None:
                    first = first.replace(tzinfo=timezone.utc)
                published_days = max(0, (datetime.now(timezone.utc) - first).days)
            except ValueError:
                published_days = 0
        measured = self.sources.get("protocol_reliability")
        return History(
            node_successes=successes,
            node_rounds=rounds,
            source_pass_rate=float(self.sources.get("source_pass_rate", 1.0)),
            protocol_reliability=None if measured is None else float(measured),
            published_days=published_days,
        )

    # -- speed ------------------------------------------------------------

    async def _measure_speed(
        self,
        conn,
        verified: Sequence[ProbeResult],
        seen_keys: dict,
        driver: "CoreDriver | None" = None,
    ) -> tuple[list[str], SpeedReport]:
        """Rank survivors, measure the top of the ranking, apply the results.

        Returns the ranking order used, and the report. Both are returned
        because the report's `deferred` map is the only record of why a node
        went unmeasured, and the caller writes it into the run report rather
        than dropping it.

        Two guards, both cheaper than a measurement:

        * **No driver → no round.** Without `driver_factory` the pipeline has
          never opened a socket, so there is nothing to read bytes through.
        * **No `--allow-network` → no round.** Probing is the half of this
          system that can touch the host's live network, and it stays opt-in.

        The driver is **passed in**, not built here. It used to be built here,
        which meant `_probe` and this method each called the factory and got a
        *separate* `SingBoxDriver` — separate workdir under /tmp, separate
        children, and this one never stopped. Verified: 75 `hub-singbox-*`
        directories accumulated under /tmp, one per round per leaked stage, at a
        rate of 2 per run against a timer that fires four times a day. The one
        owned by `root` also locked the others out of being cleaned up.
        """
        if driver is None or not self.network:
            return [], SpeedReport([], {})

        nodes = [n for n in (seen_keys.get(r.dedup_key) for r in verified) if n]
        if not nodes:
            return [], SpeedReport([], {})

        # Provisional scores, `speed_bps` still `None`, which is what makes
        # this ranking available at all. Sorting by `-total` then `dedup_key`
        # matches `tiers.rank` exactly, so the order here is the order the
        # pool will be published in rather than a second, competing one.
        provisional = sorted(
            nodes, key=lambda n: (-score_node(n, self._history(conn, n.dedup_key),
                                              _result_for(verified, n)).total, n.dedup_key)
        )
        ranked_keys = [n.dedup_key for n in provisional]

        stage = SpeedStage(driver=driver, policy=self.speed_policy, load=_host_load)
        try:
            report = await stage.measure_nodes(nodes, ranked_keys)
        except Exception as exc:  # noqa: BLE001 - a speed crash must not kill the run
            self.store.append_event(
                "speed_failed", reason=f"{type(exc).__name__}: {exc}"
            )
            return ranked_keys, SpeedReport(
                [], {key: f"stage failed: {exc}" for key in ranked_keys}
            )

        applied = apply_speed(verified, report)
        self.store.append_event(
            "speed_round",
            measured=applied,
            attempted=len(report.samples),
            deferred=len(report.deferred),
        )
        return ranked_keys, report

    # -- the run ----------------------------------------------------------

    async def run_once(self, *, token: str = "") -> dict:
        started = time.monotonic()
        run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
        report = RunReport(run_id=run_id, started_at=datetime.now(timezone.utc).isoformat())
        self.store.append_event("run", run_id=run_id)

        # 1. fetch
        fetch_client = self.sources.get("fetch_client")
        # The per-source counters are loaded from the database and handed to
        # the fetcher, because `Fetcher` is rebuilt every run and an in-memory
        # ETag cannot mean "conditional request" across a process boundary. The
        # resulting ETag/`If-None-Match` pair is only worth storing because a
        # 304 now returns the cached body — see `Fetcher.fetch_one`.
        source_states = self.store.load_source_states()
        fetcher_instance = fetcher.Fetcher(
            self._fetch_sources(),
            client=fetch_client,
            states=source_states,
        )
        items, fetch_stats = await fetcher_instance.fetch_all()
        report.errors["fetch"] = fetch_stats.failed
        if fetch_stats.disabled:
            report.errors["sources_disabled"] = len(fetch_stats.disabled)
            self.store.append_event(
                "sources_disabled", run_id=run_id, sources=fetch_stats.disabled
            )

        # 2. parse
        all_nodes: list[Node] = []
        seen_keys: dict[str, Node] = {}
        #: Nodes every source offered, before any filter. The run summary
        #: prints this as "raw"; see where it is assigned.
        total_offered = 0
        include_by_key = self._source_filters("include")
        exclude_by_key = self._source_filters("exclude")
        for item in items:
            if item.not_modified and not item.body:
                # A 304 with no cached body (cold start, or the first round
                # after the cache column was added) has nothing to parse. It is
                # an empty round, not a source failure: the URL is alive, we
                # simply have no copy of its content.
                continue
            # A source whose body is not a share-URI list gets adapted first.
            # The adapter either rewrites the body or says why it cannot, and
            # "cannot" is recorded rather than swallowed: 2663 rows refused is
            # an operator-visible fact, whereas an empty body would look
            # identical to a source that simply had nothing today.
            adapted = adapters.adapt(self._source_kinds().get(item.source, ""), item.body)
            if not adapted.ok:
                report.errors[f"adapt:{item.source}"] = 1
                self.store.append_event(
                    "adapt_refused", run_id=run_id, source=item.source, reason=adapted.reason
                )
                self._close_round(fetcher_instance, item.source, 0)
                continue
            body = self._filter_body(
                adapted.text, include_by_key, exclude_by_key, item.source
            )
            nodes, errors = uri_parser.parse_many(body, source=item.source)
            report.parse_errors += len(errors)
            # What this source offered, counted before the filters below. The
            # include/exclude pair already dropped lines it did not match, so
            # this is the count of parseable candidates, not of body lines.
            total_offered += len(nodes)
            for error in errors[:5]:
                self.store.append_event(
                    "parse_error", run_id=run_id, kind=error.kind.value, line=error.line
                )
            # A source is paired with its entry by name so `include`/`exclude`
            # and the quarantine cap find it. Matching on the URL instead is
            # wrong twice over: the URL is the database key and the name is
            # what the operator typed, and a source that changes host would
            # silently lose its history.
            #
            # The cap, though, is keyed by **URL**, not by name: `state()`,
            # `note_yield` and `is_disabled` are all addressed by the URL, so
            # `quarantine_cap(name)` read a dictionary entry that nothing ever
            # wrote and reported "0 rounds" for every source on every round —
            # a cap that never lifted, however long the source had been good.
            # `item.url` is the URL the body was fetched from and is what the
            # same source's counters were stored under.
            cap = fetcher_instance.quarantine_cap(item.url)
            kept = 0
            for node in nodes:
                if is_blocked_address(node.address):
                    report.errors["ssrf"] = report.errors.get("ssrf", 0) + 1
                    continue
                if cap is not None and kept >= cap:
                    report.errors["quarantined"] = report.errors.get("quarantined", 0) + 1
                    continue
                kept += 1
                existing = seen_keys.get(node.dedup_key)
                if existing is None:
                    seen_keys[node.dedup_key] = node
                    all_nodes.append(node)
                elif not existing.remark and node.remark:
                    # Keep the richer remark; a node seen in two sources is one
                    # node, and we want the best label for it.
                    seen_keys[node.dedup_key] = node
                    all_nodes[all_nodes.index(existing)] = node
            self._close_round(fetcher_instance, item.source, kept)

            # Pre-filter node count, i.e. what the sources offered before the
            # SSRF guard, the quarantine cap, and deduplication removed any of
            # it. This is the number the run summary prints as "N raw": it was
            # `len(items)`, which is the number of source *bodies* that
            # fetched, so a 13-source round reported "12 raw" no matter whether
            # the pool held twelve nodes or thirty-two thousand. The operator
            # reading "12 raw -> 0 verified" concluded every node was dead;
            # the truth was that 35,142 were quarantined and the count named
            # neither of them.
            report.nodes_raw = total_offered
            report.nodes_parsed = len(all_nodes)

        # 3. probe
        #
        # One driver for the whole run, created here rather than inside the two
        # stages that use it. Each call to the factory constructs a
        # `SingBoxDriver` with its own /tmp workdir, so calling it per-stage is
        # how the run ended up with two of them and cleaned up one. See
        # `_measure_speed` for what that cost and `_probe` for the other half.
        driver = self._driver_factory() if self._driver_factory else None
        try:
            results, probe_stats = await self._probe(all_nodes, driver)
        finally:
            # Stopped whatever happens, and stopped before the speed stage reads
            # the results: this is the one place the process's children are
            # reaped. A leaked driver here is both a directory under /tmp and a
            # set of sing-box children wired to nodes the run has finished with.
            if driver is not None:
                with contextlib.suppress(Exception):
                    await driver.stop()
        report.stage_survivors = probe_stats
        verified = [r for r in results if r.ok and r.stage_reached.value == "http"]

        conn = self.store.connect()
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Bring back the nodes proven working recently that this round did
            # not probe. A round samples the pool rather than testing every
            # node, so publishing only this round's survivors drops
            # provably-working nodes and makes the country list flicker between
            # generations. The window equals one probe interval, so nothing
            # older than a full re-check cycle can enter the pool.
            #
            # Rebuilt whole from `nodes.state`, never from the flat columns: a
            # node without its uuid and transport renders into an entry that
            # connects nowhere, and that failure is invisible in every count.
            # Only after a round that actually probed. Carrying nodes forward
            # fills the gaps in a sample; it does not replace sampling. The
            # worker runs every 15 minutes with no network, so it verifies
            # nothing — and with this gate absent it began republishing ~150
            # nodes from the database each quarter hour, stamped with a fresh
            # `run_id` so the generation looked newly verified while holding no
            # measurement from that hour, overwriting what the real probe had
            # just produced.
            probed = [r for r in results if r.ok and r.stage_reached.value == "http"]
            if self.recent_hours and probed:
                current = {r.dedup_key for r in verified}
                carried = 0
                for node in self.recent_nodes(conn, hours=self.recent_hours, now=now):
                    if node.dedup_key in current:
                        continue
                    current.add(node.dedup_key)
                    seen_keys[node.dedup_key] = node
                    # No timings on purpose: the scorer must see that nothing
                    # was measured this round rather than a fabricated fast
                    # result it would then rank on.
                    verified.append(
                        ProbeResult(
                            dedup_key=node.dedup_key,
                            stage_reached=Stage.HTTP,
                            ok=True,
                            exit_country=node.country,
                        )
                    )
                    carried += 1
                report.stage_survivors["carried_over"] = carried

            # 3b. speed — measured on survivors only, and ranked by a
            # provisional score.
            #
            # The ordering problem is real and is not solved by sorting on
            # latency: which nodes are worth a megabyte each is exactly the
            # question the score answers, and the score needs speed. The
            # circularity is broken by `scorer._throughput_points`, which prices
            # an unmeasured node at *half credit* rather than zero — so a
            # provisional score exists, is honest, and is a better ranking than
            # any single factor. Ranking first on a partial score and then
            # measuring the top of it is how a checker spends its budget where
            # the pool actually needs it answered.
            #
            # `driver=None` here, and that is deliberate: this stage now runs
            # after `_probe`'s `finally` has stopped it, so it gets a fresh one.
            # The pair is created once per run and stopped once per stage, which
            # is what keeps the count of live workdirs at zero.
            speed_driver = self._driver_factory() if self._driver_factory else None
            try:
                ranked_keys, speed_report = await self._measure_speed(
                    conn, verified, seen_keys, speed_driver
                )
            finally:
                if speed_driver is not None:
                    with contextlib.suppress(Exception):
                        await speed_driver.stop()
            report.stage_survivors["speed.measured"] = len(speed_report.measured)
            report.stage_survivors["speed.deferred"] = len(speed_report.deferred)
            for reason, count in _reason_counts(speed_report.deferred).items():
                report.stage_survivors[f"speed.defer:{reason}"] = count
            # The attempted-but-unmeasured half, recorded by the same bucket
            # scheme. Without this, a round where every transfer failed is
            # indistinguishable from a round where nothing was worth measuring:
            # both report `speed.measured: 0`, and the only difference between
            # them is 25 lines of `bps=None` samples nobody was counting. That
            # difference is exactly what an operator needs — "no fast nodes" is
            # a fact about the pool, "every transfer failed" is a fact about
            # this box.
            #
            # Live proof it was needed: the 2026-10-15T203636Z round recorded
            # `speed.measured 0` and `speed.defer:beyond top_n 96`, which reads
            # as "25 nodes measured, none were fast", while all 25 had actually
            # failed — most with `OSError: socks connect failed: code 1` (a
            # dead node) or `ConnectionRefusedError` on 127.0.0.1 (a driver
            # that never started the port). The pool was never the problem.
            for reason, count in _reason_counts(
                {s.dedup_key: (s.skipped_reason or "no bytes from node")
                 for s in speed_report.samples if not s.ok}
            ).items():
                report.stage_survivors[f"speed.fail:{reason}"] = count

            # 3c. Fill in the countries the probe could not measure.
            #
            # The probe asks the node itself, which is the only answer that
            # describes where traffic actually exits — and when that fails it
            # records nothing rather than guessing from the hostname, because
            # `unitedstates1.example.com` may exit anywhere and a wrong flag is
            # worse than a blank. The cost of that honesty was a client group
            # called "🌐 XX N": working nodes the user cannot pick by country,
            # which is the one thing the grouping exists for.
            #
            # Geo-IP closes it with a second *measured* answer, about the
            # address this time. It is consulted only for nodes the probe left
            # blank, so the exit country always wins, and every answer is cached
            # in the database so an address costs one lookup ever.
            geo_filled = 0
            if self.geo_lookup:
                blanks = [
                    seen_keys[r.dedup_key].address
                    for r in verified
                    if r.dedup_key in seen_keys
                    and not r.exit_country
                    and not seen_keys[r.dedup_key].country
                ]
                if blanks:
                    try:
                        found = self.geo_lookup(blanks, now=now)
                    except Exception:  # noqa: BLE001
                        # A geo lookup is an improvement, not a requirement: a
                        # round must not fail because a third-party API did.
                        found = {}
                    for key, node in list(seen_keys.items()):
                        code = found.get(node.address)
                        if code and not node.country:
                            seen_keys[key] = replace(node, country=code)
                            geo_filled += 1
            report.stage_survivors["geo.filled"] = geo_filled

            # 4. score, and record checks for the history table
            entries = []
            for result in verified:
                node = seen_keys.get(result.dedup_key)
                if node is None:
                    continue
                # `Node.country` is documented as "measured, filled in by the
                # prober": the label on a share URI is a claim, and the exit
                # country from `cdn-cgi/trace` is the measurement. Taking the
                # measurement when there is one is what makes the landing page's
                # country groups true rather than decorative — otherwise every
                # group falls back to "unknown", which is where they were.
                if result.exit_country:
                    node = replace(node, country=result.exit_country)
                    seen_keys[result.dedup_key] = node
                history = self._history(conn, result.dedup_key)
                computed = score_node(node, history, result, self.weights)
                entries.append((node, computed, history.node_rounds + 1))
                conn.execute(
                    "INSERT INTO checks (dedup_key, run_at, ok, stage, http_ms, jitter_ms, error)"
                    " VALUES (?, ?, 1, 'http', ?, ?, '')",
                    (result.dedup_key, now, result.http_ms, result.jitter_ms),
                )

            failed = [r for r in results if not r.ok]
            for result in failed:
                conn.execute(
                    "INSERT INTO checks (dedup_key, run_at, ok, stage, http_ms, jitter_ms, error)"
                    " VALUES (?, ?, 0, ?, ?, ?, ?)",
                    (
                        result.dedup_key,
                        now,
                        result.stage_reached.value,
                        result.http_ms,
                        result.jitter_ms,
                        result.error,
                    ),
                )

            # upsert the node index
            conn.executemany(
                "INSERT INTO nodes (dedup_key, protocol, address, port, country, source, first_seen, last_ok, score, rounds, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(dedup_key) DO UPDATE SET"
                "   last_ok=excluded.last_ok, score=excluded.score,"
                "   rounds=excluded.rounds, country=excluded.country,"
                "   state=excluded.state",
                [
                    (
                        node.dedup_key,
                        node.protocol.value,
                        node.address,
                        node.port,
                        node.country,
                        node.source,
                        now,
                        now if result_ok else None,
                        computed.total,
                        rounds,
                        # Stored whole: the flat columns identify a node, they
                        # do not reconstruct one.
                        node_to_json(node),
                    )
                    for node, computed, rounds in entries
                    for result_ok in (True,)
                ],
            )
            conn.commit()

            report.nodes_verified = len(entries)

            # 5. tier + 6. render + validate + publish
            if len(entries) >= self.min_pool:
                built = tierlib.build_tiers(entries, self.policies)
                generation, sha = self._publish(built, report)
                if generation:
                    report.generation = generation
                    report.sha256 = sha
                else:
                    report.fatal = True
                    report.fatal_reason = "no payload passed validation"
            else:
                report.errors["pool_too_small"] = len(entries)

        finally:
            conn.close()

        report.finished_at = datetime.now(timezone.utc).isoformat()
        report_duration = round(time.monotonic() - started, 2)
        # `report.as_dict()` already carries `run_id`, so it must not be passed
        # again explicitly: `append_event(**fields)` would receive the same
        # keyword twice and raise TypeError from inside the node that logs the
        # run summary — a crash in the reporting path, after the real work is
        # done, that would lose the generation report.
        self.store.append_event("run_done", **report.as_dict())
        self.store.append_event(
            "metrics",
            run_id=run_id,
            duration_s=report_duration,
            verified=report.nodes_verified,
            published=report.published,
            parse_errors=report.parse_errors,
        )
        return report.as_dict()

    # -- publish ----------------------------------------------------------

    def _publish(self, built: dict, report: RunReport) -> tuple[str, str]:
        """Write every tier payload into a new immutable generation.

        Returns ("", "") if nothing could be produced. On success the previous
        pointer stays live until the flip, so a crash mid-write is invisible.
        """
        ordered = sorted(
            (policy.tier, select) for policy, select in
            ((p, built.get(p.tier)) for p in self.policies) if select
        )
        if not ordered:
            return "", ""

        # Generation name is content-derived: the same pool in the same order
        # produces the same id, which makes deduplication and rollback obvious.
        #
        # `kind` and `cc` are carried explicitly rather than re-parsed from
        # `name` when the `publishes` rows are written below. Recovering them
        # by splitting the filename is what the old code did, and it cannot
        # work: `sing-box` is the only core name with a dash, so
        # `name.split("-")[1]` yields "sing" for the whole-tier payloads and
        # the two-letter *country* code for the shards. A row that cannot say
        # which payload it is cannot be keyed, summed, or compared against the
        # previous generation — and four country shards in the same format
        # would collide on (core, fmt) alone, silently keeping only the last.
        # It is `core` for a whole-tier payload, and "" for a country shard
        # (whose country is `cc`).
        #
        #: (tier, name, payload, nodes, kind, cc)
        payloads: list[tuple[str, str, bytes, int, str, str]] = []
        for tier, selected in ordered:
            nodes = [entry.node for entry in selected]
            for core in ("xray", "sing-box", "mihomo"):
                for fmt in (Format.BASE64, Format.SINGBOX, Format.CLASH):
                    if fmt is Format.SINGBOX and core == "xray":
                        continue  # Xray clients do not read sing-box JSON
                    if fmt is Format.CLASH and core == "xray":
                        continue
                    params = RenderParams(
                        fmt=fmt,
                        client_core=core,
                        title=f"hub-{tier.value}-{core}",
                        cache_id=hashlib.sha256(
                            "".join(n.dedup_key for n in nodes).encode()
                        ).hexdigest()[:16],
                    )
                    try:
                        payload, included = render_validated(
                            nodes, params, validate=self._validation_callback
                        )
                    except ValueError:
                        report.errors[f"render:{tier.value}:{core}:{fmt.value}"] = 1
                        continue
                    if not payload:
                        continue
                    name = f"{tier.value}-{core}.{fmt.value}"
                    payloads.append((tier.value, name, payload, len(included), core, ""))

            # The Xray dialect: one outbound per node, one `leastPing` balancer
            # per country, and an `observatory` that probes them. This is the
            # payload that gives a client automatic failover — Happ hands a
            # JSON body to the Xray core verbatim, so the balancer runs there
            # and re-points traffic when a node dies, which the hub cannot do
            # for a client it does not carry traffic for.
            #
            # Validated with the real `xray run -test` when a binary is
            # present, and skipped with the payload still emitted when it is
            # not: the hub does not run Xray, so its absence is a missing
            # check, not a reason to publish nothing.
            params = RenderParams(
                fmt=Format.SINGBOX,
                client_core="xray",
                title=f"hub-{tier.value}-xray",
                cache_id=hashlib.sha256(
                    "".join(n.dedup_key for n in nodes).encode()
                ).hexdigest()[:16],
            )
            try:
                payload, included = render_validated(
                    nodes, params, validate=self._xray_validator
                )
            except ValueError:
                report.errors[f"render:{tier.value}:xrayjson"] = 1
            else:
                if payload:
                    payloads.append(
                        (tier.value, f"{tier.value}-xray.json",
                         payload, len(included), "xray", "")
                    )

            # A de-duplicated base64 variant: one node per country.
            #
            # For clients that cannot group — Happ's documentation describes a
            # subscription body as a URI list or a JSON array and never mentions
            # proxy groups — the `urltest` grouping the other payloads carry is
            # invisible, and the flat list shows every node: four
            # "Finland" entries in a row. With one node per country the list
            # itself is a country picker. The kept node is the best-scoring
            # one, because `nodes` arrives ranked.
            #
            # Base64 only: it is the flat dialect, and the JSON/YAML payloads
            # keep their groups precisely because those clients *can* fail over
            # within a country, which is strictly better than a single node.
            # Pre-rendered rotation variants, one file per rotation round.
            #
            # The API's hot path reads a file and nothing else — it never
            # renders, because a subscription fetch must not depend on the
            # renderer being importable or fast. So rotation cannot be computed
            # per request; it is baked here, and the API picks a file by
            # request counter. That keeps the hot path a `read_bytes()` and
            # keeps every variant immutable and content-addressed with the rest
            # of the generation.
            #
            # One file per round, `rounds` = the largest country group, so
            # every round has a node to offer for every country. A smaller
            # country simply repeats its node sooner, which is correct: it has
            # no alternative to offer.
            rounds = max(
                (
                    len([n for n in nodes if (n.country or "").upper() == cc])
                    for cc in {(n.country or "").upper() for n in nodes}
                ),
                default=1,
            )
            for rotation in range(max(1, rounds)):
                params = RenderParams(
                    fmt=Format.BASE64,
                    client_core="xray",
                    title=f"hub-{tier.value}-unique",
                    cache_id=hashlib.sha256(
                        "".join(n.dedup_key for n in nodes).encode()
                    ).hexdigest()[:16],
                    one_per_country=True,
                    rotation=rotation,
                )
                try:
                    payload, included = render_validated(
                        nodes, params, validate=self._validation_callback
                    )
                except ValueError:
                    report.errors[f"render:{tier.value}:unique:{rotation}"] = 1
                    continue
                if not payload:
                    continue
                # `-rot{N}`: the API resolves `verified-unique.base64` to one of
                # these by counter. The unsuffixed name was the pre-rotation
                # shape, and no file carries it now — a stale client cache for
                # that exact name would 404 rather than serve a node we did not
                # choose.
                payloads.append(
                    (tier.value, f"{tier.value}-unique-rot{rotation}.base64",
                     payload, len(included), "xray", "")
                )

            try:
                shards = country_shards(nodes, validate=self._validation_callback)
            except ValueError:
                report.errors[f"render:{tier.value}:country"] = 1
                shards = []
            for shard in shards:
                # `{tier}-{CC}.{fmt}`: the dot is what keeps this from reading
                # as `{tier}-{core}.{fmt}`. With a dash, `verified-NL-singbox`
                # looks like a core called "NL", and `_payload_path` (and every
                # future reader of these names) has to guess which segment is
                # which. A country code is two letters, a core is never two
                # letters, and the dot makes the split structural instead of a
                # heuristic. Clients cache these by URL, so the name is also
                # the API.
                payloads.append(
                    (tier.value, f"{tier.value}-{shard.cc}.{shard.fmt.value}",
                     shard.payload, shard.included, "", shard.cc)
                )

        if not payloads:
            return "", ""
        digest = hashlib.sha256()
        for _tier, name, payload, _count, _kind, _cc in sorted(payloads, key=lambda row: (row[0], row[1])):
            encoded_name = name.encode("utf-8")
            digest.update(len(encoded_name).to_bytes(4, "big"))
            digest.update(encoded_name)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
        content_sha = digest.hexdigest()
        generation = "gen-" + content_sha[:12]

        # Serialize generation reuse, DB indexing, pointer changes, and cleanup.
        with _publish_lock(self.store.data / ".publish.lock"):
            # A matching content hash is a no-op only if the current directory
            # is complete and every payload still matches the manifest.
            if self.store.current_generation() == generation and self._generation_complete(
                self.store.generation_path(generation), content_sha
            ):
                report.published, report.tier_counts = _published_counts(payloads)
                return generation, content_sha

            target = self.store.generation_path(generation)
            if not self._generation_complete(target, content_sha):
                temporary = Path(tempfile.mkdtemp(prefix=f".{generation}-", dir=self.store.generations))
                try:
                    manifest = {
                        "generation": generation,
                        "sha256": content_sha,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "payloads": [
                            {"tier": t, "name": n, "nodes": c,
                             "sha256": hashlib.sha256(payload).hexdigest()}
                            for t, n, payload, c, _k, _cc in payloads
                        ],
                    }
                    for _tier, name, payload, _count, _kind, _cc in payloads:
                        (temporary / name).write_bytes(payload)
                    (temporary / "manifest.json").write_text(
                        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
                    )
                    if target.exists():
                        import shutil
                        shutil.rmtree(target)
                    os.replace(temporary, target)
                except Exception:
                    import shutil
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise
            else:
                manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))

            # Drift check: a >40% shrinkage is logged loudly but published anyway.
            previous = self._previous_count()
            if previous and report.nodes_verified < previous * 0.6:
                self.store.append_event(
                    "pool_drift", generation=generation,
                    previous=previous, current=report.nodes_verified,
                )

            # Persist the index before switching the live pointer. A failed DB
            # write therefore leaves the prior generation live and serviceable.
            conn = self.store.connect()
            try:
                conn.executemany(
                    "INSERT INTO publishes (generation, sha256, tier, core, fmt, node_count, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(generation, tier, core, fmt) DO UPDATE SET"
                    " node_count=excluded.node_count, sha256=excluded.sha256",
                    [
                        (
                            generation, content_sha, t, kind or f"cc:{cc}",
                            n.rsplit(".", 1)[-1], c, manifest["created_at"],
                        )
                        for t, n, _payload, c, kind, cc in payloads
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            self.store.flip_pointer(generation, content_sha)
            removed = self.store.retain(3)

        report.published, report.tier_counts = _published_counts(payloads)
        self.store.append_event(
            "publish", generation=generation, payloads=len(payloads),
            nodes=report.published, removed_generations=removed,
        )
        return generation, content_sha

    @staticmethod
    def _generation_complete(directory: Path, content_sha: str) -> bool:
        """Verify manifest identity and every listed payload before reuse/serve."""
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("sha256") != content_sha:
                return False
            payloads = manifest["payloads"]
            if not payloads:
                return False
            for item in payloads:
                name = item["name"]
                if Path(name).name != name or name in {".", ".."}:
                    return False
                path = directory / name
                if not path.is_file():
                    return False
                if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    return False
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _validate_payload(self, text: str, fmt: Format) -> bool:
        """Validate a rendered dialect without making network requests."""
        if fmt is Format.BASE64:
            import base64
            try:
                decoded = base64.b64decode(text, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return False
            nodes, errors = uri_parser.parse_many(decoded)
            return bool(nodes) and not errors
        if fmt is Format.SINGBOX:
            try:
                config = json.loads(text)
            except json.JSONDecodeError:
                return False
            binary = os.environ.get("SINGBOX_BIN", "")
            if not binary:
                from .singbox import find_binary
                binary = find_binary() or ""
            if not binary:
                return False
            import subprocess
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
                json.dump(config, handle)
                handle.flush()
                try:
                    result = subprocess.run(
                        [binary, "check", "--config", handle.name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return False
            return result.returncode == 0
        if fmt is Format.CLASH:
            try:
                import yaml
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                return False
            return isinstance(data, dict) and isinstance(data.get("proxies"), list)
        return False


    def _xray_validator(self, text: str, fmt: Format) -> bool:
        """`xray run -test` on the rendered config, or a structural fallback.

        The real core is the only authority on whether a config starts: a
        structurally perfect JSON that Xray refuses is still a dead
        subscription, and the failure would surface on the user's device. So
        the binary is used when present.

        When it is not — the hub does not run Xray, and this host only has one
        for testing — the fallback checks the load-bearing invariant instead of
        returning `True` blindly: the config must parse, and it must contain a
        balancer for every country it declares outbounds for. That is the part
        whose absence would silently remove the feature this payload exists to
        provide, and it is checkable without the core.
        """
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return False

        # The body is Happ's *envelope*: a JSON array whose elements are handed
        # to the Xray core one at a time. The core itself refuses the array
        # (`cannot unmarshal array into Go value of type conf.Config`), so each
        # element is what gets checked — and one bad country in the array is one
        # country that cannot connect.
        if not isinstance(body, list) or not body:
            return False

        binary = os.environ.get("XRAY_BIN", "") or shutil.which("xray")
        for entry in body:
            if not isinstance(entry, dict):
                return False
            if binary:
                # `remarks`/`meta` are Happ's fields, not Xray's; the core
                # rejects unknown keys, so they are stripped for the check only.
                probe = {k: v for k, v in entry.items() if k not in ("remarks", "meta")}
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", suffix=".json"
                ) as handle:
                    json.dump(probe, handle)
                    handle.flush()
                    try:
                        result = subprocess.run(
                            [binary, "run", "-test", "-c", handle.name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=20,
                            check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        return False
                if result.returncode != 0:
                    return False
                continue
            # Structural fallback when no core is present: an element without a
            # balancer, or one whose observatory does not cover its own nodes,
            # has lost the failover this payload exists to provide.
            balancers = entry.get("routing", {}).get("balancers")
            if not isinstance(balancers, list) or not balancers:
                return False
            if not entry.get("observatory", {}).get("subjectSelector"):
                return False
            for balancer in balancers:
                if not balancer.get("selector"):
                    return False
        return True

    def recent_nodes(self, conn, *, hours: int, now: str) -> list[Node]:
        """Nodes proven working within `hours` of `now`, rebuilt whole.

        The pool is the union of what has been *proven working recently*, not
        the intersection of what one round happened to probe. Measured on the
        live pool: four consecutive rounds verified 68, 239, 72 and 57 nodes and
        shared 316 distinct nodes between them, while each publication used only
        its own round — so countries appeared and disappeared between
        generations for no reason a user could see.

        The window is a freshness bound, not an optimisation: a check from
        longer ago than one probe cycle is evidence about the past, and a node
        that has since died must not be published forever. The caller sets the
        window to the probe cadence.

        A node whose stored state cannot be rebuilt is **skipped**, not faked.
        Rebuilding from the flat columns produces a placeholder with no uuid or
        transport, which validates, renders, and connects nowhere — the failure
        that looks like success.
        """
        from datetime import datetime, timedelta

        from .store_state import node_from_json

        try:
            cutoff = datetime.fromisoformat(now) - timedelta(hours=hours)
        except ValueError:
            return []
        rows = conn.execute(
            "SELECT DISTINCT c.dedup_key, n.state FROM checks c"
            " JOIN nodes n ON n.dedup_key = c.dedup_key"
            " WHERE c.stage = 'http' AND c.ok = 1 AND c.run_at >= ?",
            (cutoff.isoformat(),),
        ).fetchall()
        out: list[Node] = []
        for _key, state in rows:
            node = node_from_json(state) if state else None
            if node is not None:
                out.append(node)
        return out

    def _validation_callback(self, text: str, fmt: Format) -> bool:
        """Apply a supplied validator; otherwise use production validation.

        The injected validator is the hermetic-test seam: it lets a test publish
        without a real `sing-box` binary or `yaml`. When none is injected this
        is the *only* thing standing between a rendered payload and a client,
        so the fallback must be the real implementation above — not a second
        definition of the same name, which is what silently shadowed it.
        """
        if self._validate is not None:
            return bool(self._validate(text, fmt))
        return bool(self._validate_payload(text, fmt))

    def _previous_count(self) -> int:
        """Node count of the previous generation, for the drift check.

        Whole-tier payloads only, and the maximum rather than the sum: the
        manifest lists ~15 payloads per generation (3 cores x 3 formats plus
        one file per country), each carrying the same nodes again, so summing
        them reported 335 for a 39-node pool. The drift check compares that
        against `report.nodes_verified` — the number of distinct nodes that
        survived probing — so a per-payload sum on one side and a node count on
        the other makes the comparison meaningless: it can never trigger, and a
        pool collapsing to a tenth of its size would look like a quiet day.
        """
        current = self.store.current_generation()
        manifest_path = self.store.generation_path(current) / "manifest.json" if current else None
        if manifest_path and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                counts = [
                    p["nodes"]
                    for p in manifest.get("payloads", [])
                    # A whole-tier payload is `{tier}-{core}.{fmt}`; a shard is
                    # `{tier}-{CC}.{fmt}`. The dash-count is not the test — a
                    # country code and a core are both single dash-segments.
                    # The core is the one that is longer than two characters,
                    # which is exactly what makes the shard naming safe.
                    if "-" in p.get("name", "")
                    and len(p["name"].split("-", 1)[1].rsplit(".", 1)[0]) > 2
                ]
                return max(counts) if counts else 0
            except (json.JSONDecodeError, KeyError, OSError):
                return 0
        return 0


async def run_once(
    root: Path,
    *,
    sources: dict | None = None,
    driver_factory: Optional[Callable[[], CoreDriver]] = None,
    validate: Optional[Callable[[str, Format], bool]] = None,
    concurrency: Optional[Concurrency] = None,
    connect: Optional[Callable] = None,
    handshake: Optional[Callable] = None,
    network: bool = False,
    speed_policy: Optional[SpeedPolicy] = None,
) -> dict:
    """Convenience wrapper for the CLI and for tests."""
    pipeline = Pipeline(
        root=root,
        sources=sources,
        driver_factory=driver_factory,
        validate=validate,
        concurrency=concurrency,
        connect=connect,
        handshake=handshake,
        network=network,
        speed_policy=speed_policy,
    )
    return await pipeline.run_once()
