"""Source ingestion. Read-only by default: raw GitHub content and jsDelivr.

The original concept's "GitHub Actions runs the scraper" is not viable as a
*scheduler* (verified: 64% of 15-minute cron slots produced a run over 7 days,
median 7.4 min delay, and schedules auto-disable after 60 days of repo
inactivity with no notification). GitHub is still a perfectly good *source* of
raw files.

Two ingestion rules that protect both sides:

1. **Never use the anonymous REST API.** It is 60/hr and was already exhausted
   on this box. Everything goes through `raw.githubusercontent.com` or jsDelivr,
   both verified reachable and unmetered.
2. **Conditional requests on every source.** An `ETag`/`If-None-Match` 304 costs
   nothing and lets us skip parsing entirely. Sources that stop answering get a
   backoff, and a source returning 20 consecutive empty rounds is disabled.

Because `Fetcher` is rebuilt for every `hub run`, nothing it remembers can mean
"consecutive" unless it is handed in and given back. That is what `states` is:
`{url: {etag, body, empty_rounds, rounds, enabled, ...}}` loaded from the
`sources` table before the fetch and replaced by the caller afterwards. The
two consequences are load-bearing:

* **A 304 must return the cached body, not an empty one.** `pipeline.run_once`
  builds its entire node pool from fetched bodies, so "skip parsing on a 304"
  would mean an unchanged source contributes nothing and the round publishes an
  empty generation. That looks identical to a broken checker, so the cache is
  not an optimisation — it is what makes conditional fetching safe at all.
* **The counters must round-trip.** `empty_rounds` resetting to 0 every run is
  a circuit breaker that never trips.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Mapping, Optional, Sequence

#: A browser-grade UA with a real contact is what keeps abuse desks from
#: treating the crawler as a scanning bot (documented precedent: an abuse report
#: for a scraping SOCKS proxy at 1-4 requests/host/day). Be boring, be reachable.
USER_AGENT = (
    "hub-node-index/0.1 (+https://example.com/abuse; node availability monitor)"
)

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 10.0

#: A source returning this many consecutive empty rounds is disabled.
EMPTY_ROUND_LIMIT = 20

#: Rounds of history before a source stops being capped.
#:
#: The cap was 50 nodes for 10 rounds, and that was the wrong instrument. It
#: limits *volume*, but volume is not what makes a source dangerous here: every
#: node it lists is independently probed before it can be published, so a source
#: listing 7000 dead links contributes 7000 failures and nothing else. What the
#: cap actually did was gate the pool's growth on wall-clock time — a large
#: source needed `nodes / 50 * 6h` to be fully considered, which for the ~7000
#: node source added on 2026-10-16 is 35 days. The pool stayed thin for weeks
#: while the sources that could fill it sat throttled.
#:
#: The real defences, which do not depend on the source being new:
#:   * `probe` — nothing is published unless it survives TCP, TLS, config and
#:     two HTTP rounds;
#:   * `max_per_source` in `tiers.py` — bounds what one source can contribute to
#:     the *published* pool, where dominance would actually matter;
#:   * `EMPTY_ROUND_LIMIT` — a source that answers with nothing is dropped.
#:
#: So the cap is now generous enough not to be the binding constraint, and the
#: round count is what still distinguishes "new" from "proven".
QUARANTINE_ROUNDS = 10

#: The most nodes a quarantined source may contribute in one round.
#:
#: 2000, not 50. Chosen from what the host can actually verify rather than from
#: caution about the source: the probe does ~11600 nodes in ~9 minutes against
#: a 6-hour timer, so even the largest known source fits with two orders of
#: magnitude of headroom. A source adding more than this in a single round is
#: not a source whose volume needs capping — it is a source that should be read
#: across several rounds, which is what this value does.
QUARANTINE_CAP = 2000

#: `Retry-After` in either legal form: delta-seconds (`120`) or an HTTP-date
#: (`Wed, 21 Oct 2026 07:28:00 GMT`). Both are parsed; anything else falls back
#: to the exponential backoff, which is what the spec allows.
_RETRY_AFTER_SECONDS = re.compile(r"^\s*(\d+)\s*$")


@dataclass(frozen=True)
class Source:
    url: str
    name: str = ""
    enabled: bool = True
    #: If set, only parse lines matching any of these regexes.
    include: tuple[str, ...] = ()
    #: If set, drop lines matching any of these regexes.
    exclude: tuple[str, ...] = ()
    #: Which adapter to run the body through before `parse_many`. Empty means
    #: the body is already a share-URI list. Declared per source rather than
    #: inferred from the URL: a mirror on a different host serves the same
    #: *shape*, and a URL pattern would stop matching the day it moves.
    kind: str = ""

    @property
    def key(self) -> str:
        return self.name or self.url


@dataclass(frozen=True)
class RawItem:
    """One source's raw body plus how we got it."""

    source: str
    url: str
    body: str
    fetched_at: float
    not_modified: bool = False
    etag: str = ""


@dataclass
class FetchStats:
    attempted: int = 0
    fetched: int = 0
    not_modified: int = 0
    failed: int = 0
    bytes_read: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    durations_ms: dict[str, float] = field(default_factory=dict)
    disabled: list[str] = field(default_factory=list)

    def record_error(self, label: str) -> None:
        self.errors[label] = self.errors.get(label, 0) + 1


class Fetcher:
    """Pulls source bodies. HTTP is behind an injected client for testing."""

    def __init__(
        self,
        sources: Sequence[Source],
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        client=None,
        states: Optional[Mapping[str, Mapping]] = None,
    ) -> None:
        self.sources = list(sources)
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._client = client
        # Seeded from the database by the caller. A race between two `hub run`
        # processes is not a scenario this project has, so these are plain
        # reads and writes with no locking beyond SQLite's own.
        self.states: dict[str, dict] = {}
        for url, state in (states or {}).items():
            self.states[url] = dict(state)
        #: `{url: node count this round}`, filled by `note_yield` as the caller
        #: parses. The circuit breaker and the quarantine cap both read it,
        #: which is why the counts come back in rather than being computed here:
        #: `Fetcher` fetches bodies, it does not parse them, so it cannot know
        #: how many nodes a body was worth on its own.
        self.yields: dict[str, int] = {}
        #: Sources disabled by the circuit breaker during this run, so the
        #: caller persists the flag instead of rediscovering it from a log.
        self.newly_disabled: list[str] = []
        self._etags: dict[str, str] = {
            url: (state.get("etag") or "")
            for url, state in self.states.items()
            if state.get("etag")
        }

    def state(self, url: str) -> dict:
        """This source's counters, defaulted rather than absent.

        Defaulted *here* rather than at the call site so every reader agrees on
        what "no history" means: zero rounds, zero empties, not disabled, no
        cap. `load_source_states` deliberately omits unknown sources, and this
        is the one place the omission becomes a value.
        """
        return self.states.setdefault(
            url,
            {"enabled": 1, "rounds": 0, "empty_rounds": 0, "etag": "", "body": ""},
        )

    def note_yield(self, url: str, nodes: int) -> None:
        """Record how many nodes a source contributed this round.

        Called once per source after parsing, before the next fetch round, so
        the counters describe a *completed* round. Calling it before parsing
        would count a body as empty every time.
        """
        self.yields[url] = nodes

    def is_disabled(self, url: str) -> bool:
        """Whether the circuit breaker has this source turned off.

        Checked against the state carried into the fetcher *and* against
        `newly_disabled`, so a source tripped this round is not fetched again
        if `fetch_all` is called more than once.
        """
        return url in self.newly_disabled or not self.state(url).get("enabled", 1)

    async def fetch_all(
        self, *, concurrency: int = 5, skip_disabled: bool = True
    ) -> tuple[list[RawItem], FetchStats]:
        # `attempted` is deliberately not seeded here. `fetch_one` increments it
        # once per HTTP request it actually issues, so seeding it with the
        # source count made "sources" and "requests" the same number that were
        # always off by one — a source retried twice counted as 3 with nothing
        # to distinguish the concurrency from the retries. `attempted` means
        # requests issued; `len(self.sources)` means sources, and callers that
        # want it can ask for it.
        stats = FetchStats(attempted=0)
        sem = asyncio.Semaphore(concurrency)
        live: list[Source] = []
        for source in self.sources:
            # A source can be disabled in the YAML (`enabled: false`) or by the
            # circuit breaker during an earlier run. Both are honoured here,
            # but `skip_disabled=False` fetches them anyway, which is what the
            # audit script wants: re-verifying a source the breaker has turned
            # off is exactly the question it exists to answer.
            if source.enabled and (not skip_disabled or not self.is_disabled(source.url)):
                live.append(source)
            else:
                stats.disabled.append(source.key)

        async def _one(source: Source) -> Optional[RawItem]:
            async with sem:
                return await self.fetch_one(source, stats)

        items = await asyncio.gather(*[_one(s) for s in live]) if live else []
        return [i for i in items if i is not None], stats

    async def fetch_one(self, source: Source, stats: Optional[FetchStats] = None) -> Optional[RawItem]:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        etag = self._etags.get(source.url)
        if etag:
            headers["If-None-Match"] = etag

        last_error = ""
        for attempt in range(self.retries):
            if stats is not None:
                stats.attempted += 1
            started = time.monotonic()
            try:
                body, status, response_headers = await self._get(source.url, headers)
            except Exception as exc:  # noqa: BLE001 - a source must never kill the run
                last_error = f"{type(exc).__name__}: {exc}"
                if stats is not None:
                    stats.record_error("network")
                await asyncio.sleep(self.backoff * (attempt + 1))
                continue

            elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
            if stats is not None:
                stats.durations_ms[source.key] = elapsed_ms

            if status == 304:
                if stats is not None:
                    stats.not_modified += 1
                # Not modified does not mean "nothing to do": the body we hold
                # is still the current content of that URL, so it is returned
                # for parsing with `not_modified=True` set for the metrics. The
                # alternative — returning an empty body — reads in the pipeline
                # as "this source produced nothing", so a round where every
                # source 304'd would publish an empty generation.
                #
                # The cache is per-URL and is only ever the last body that
                # fetched successfully, so this cannot resurrect a stale node
                # set beyond one round of the source's own publishing cadence.
                cached = self.state(source.url).get("body") or ""
                return RawItem(
                    source.key, source.url, cached, time.monotonic(), not_modified=True
                )

            if status >= 400:
                last_error = f"HTTP {status}"
                if stats is not None:
                    stats.record_error(f"http_{status}")
                # 429 and 503 are the statuses that say how long to wait, and a
                # source that is asking for a slower cadence gets one: the flat
                # `backoff * (attempt + 1)` exists as a fallback, not as the
                # cheapest thing to send. Every other 4xx/5xx is retried on the
                # same schedule because a transient 502 is not a rate-limit
                # signal and backing off hard on it just thins the pool.
                delay = _retry_after_seconds(response_headers.get("retry-after", ""))
                if delay is None:
                    delay = self.backoff * (attempt + 1)
                await asyncio.sleep(delay)
                continue

            new_etag = response_headers.get("etag", "")
            if new_etag:
                self._etags[source.url] = new_etag
                self.state(source.url)["etag"] = new_etag
            # The body is cached *as fetched*, before any adapter runs on it.
            # `run_once` adapts the body itself, so caching the adapted form
            # would lose the distinction between "the source changed" and "we
            # changed how we read it" — and on the day the adapter is fixed, a
            # 304 would keep serving the pre-fix body for one more round.
            self.state(source.url)["body"] = body
            if stats is not None:
                stats.fetched += 1
                stats.bytes_read += len(body)
            return RawItem(source.key, source.url, body, time.monotonic(), etag=new_etag)

        # A round where this source yielded nothing. Not the same as a source
        # that yielded *nothing new*: an unreachable source and a body that
        # parsed to zero nodes both thin the pool, and both are what the limit
        # counts. The caller cannot report a yield for a source it never got a
        # body for, so this is closed here rather than left for it.
        if stats is not None:
            stats.failed += 1
            stats.record_error("exhausted")
        self._close_round(source, 0)
        self._warn(f"source {source.key} failed after {self.retries} attempts: {last_error}")
        return None

    # -- round accounting --------------------------------------------------
    #
    # One entry per method, one rule: **`rounds` is incremented in exactly one
    # place**, `_close_round`, once per completed round. Two callers bumping it
    # was not a harmless redundancy — `begin_round` followed by `end_round`
    # counted one round as two, so a source reached `QUARANTINE_ROUNDS` of
    # "history" in half the rounds, and the quarantine cap lifted on a source
    # that had proven nothing like as much as the counter claimed.

    def _close_round(self, source: Source, nodes: int) -> None:
        """Record one completed round and decide whether to disable the source.

        `nodes` is what the round actually contributed to the pool, counted by
        the caller after its own filters — so this is the single writer for
        both counters, and every path that completes a round goes through it.

        Two outcomes, and they are different:
        * `nodes > 0` clears the empty streak. The limit is about *consecutive*
          empties, so a source alternating empty and productive is a different
          problem from a permanently dead one, and treating them alike would
          disable healthy sources on a bad cadence.
        * `nodes == 0` advances the streak, and at `EMPTY_ROUND_LIMIT` the
          source is disabled *and* recorded in `newly_disabled` so the caller
          can persist the flag instead of rediscovering it from a log line.
        """
        state = self.state(source.url)
        state["rounds"] = int(state.get("rounds") or 0) + 1
        if nodes > 0:
            state["empty_rounds"] = 0
            state["last_ok"] = _utcnow()
            return
        state["empty_rounds"] = int(state.get("empty_rounds") or 0) + 1
        if state["empty_rounds"] >= EMPTY_ROUND_LIMIT:
            state["enabled"] = 0
            if source.url not in self.newly_disabled:
                self.newly_disabled.append(source.url)

    def begin_round(self, source: Source) -> None:
        """Note that a round is starting for this source.

        Deliberately does *not* count anything. `rounds` means "completed
        rounds", because that is what the quarantine threshold measures: a
        source in the middle of a round that yields nothing must not gain the
        trust it is about to earn or lose. Counting on start made an interrupted
        round indistinguishable from a finished one.
        """
        self.state(source.url)

    def end_round(self, source: Source, nodes: int) -> None:
        """Close the round. See `_close_round`; this is the public spelling."""
        self._close_round(source, nodes)

    def quarantine_cap(self, url: str) -> Optional[int]:
        """How many nodes this source may contribute this round.

        A source with fewer than `QUARANTINE_ROUNDS` rounds of history is new,
        and new is not the same as trustworthy: one unvetted URL listing ten
        thousand dead nodes can set the whole pool's character on its first
        day. The cap is a ratio the caller applies while parsing, so the
        source still contributes — it just cannot crowd out the ones with a
        track record. `None` means uncapped.
        """
        state = self.state(url)
        if int(state.get("rounds") or 0) >= QUARANTINE_ROUNDS:
            return None
        return QUARANTINE_CAP

    # -- transport --------------------------------------------------------

    async def _get(self, url: str, headers: dict) -> tuple[str, int, dict]:
        client = self._client
        if client is not None:
            return await client(url, headers)
        return await self._http_get(url, headers)

    async def _http_get(self, url: str, headers: dict) -> tuple[str, int, dict]:
        """asyncio-native HTTP. No third-party dependency for the MVP."""
        import urllib.request

        def _sync() -> tuple[str, int, dict]:
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return (
                        response.read().decode(charset, errors="replace"),
                        response.status,
                        dict(response.headers),
                    )
            except urllib.error.HTTPError as exc:
                return "", exc.code, dict(exc.headers or {})

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)

    @staticmethod
    def _warn(message: str) -> None:
        # The pipeline reports through the event log; a source failure is an
        # expected event, not an exception.
        print(f"[fetcher] {message}")


def _retry_after_seconds(header: str, *, now: float | None = None) -> Optional[float]:
    """Parse a `Retry-After` header into seconds to sleep.

    Both forms RFC 7231 defines are handled, because a server may legally send
    either and honouring only the integer form silently ignores the date form
    while still looking implemented:

    * `Retry-After: 120` — delta-seconds, taken literally.
    * `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` — an absolute HTTP-date,
      converted relative to the current time and clamped at 0, so a date that
      has already passed sleeps nothing rather than a negative number.

    Returns `None` for an absent or unparseable value: "I could not read this"
    and "wait zero seconds" are different, and guessing the second would hammer
    a host that just asked us to slow down. Callers fall back to their own
    backoff in that case.
    """
    if not header:
        return None
    match = _RETRY_AFTER_SECONDS.match(header)
    if match:
        return float(match.group(1))
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    delta = when.timestamp() - (now if now is not None else time.time())
    # A date in the past is a stale instruction, not a reason to skip retrying:
    # clamp to zero so the caller still backs off on its own schedule.
    return max(0.0, delta)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Source list loading
# --------------------------------------------------------------------------- #


#: The per-source fields this project reads. A key indented under a `- url:`
#: entry that is not one of these is a typo, and saying so beats passing it to
#: `Source(**current)`, where it becomes a `TypeError` about a keyword the
#: dataclass has never heard of.
SOURCE_FIELDS = ("url", "name", "enabled", "include", "exclude", "kind")

#: File-level knobs, with the type each one is coerced to. A column-0 key that
#: is not `sources` and not listed here is a typo, and naming it beats dropping
#: it: a silently dropped setting is indistinguishable from one that was never
#: set, which is precisely how these knobs went unread — the reader returned
#: them to nobody and the pipeline read defaults without complaining.
FILE_SETTINGS: Mapping[str, type] = {
    "base_url": str,
    "canary_token": str,
    "source_pass_rate": float,
    "protocol_reliability": float,
    #: Telegram username without the `@`. Published by `/api/v1/bot` so the
    #: landing page's country cards can deep-link into the bot instead of
    #: carrying a hard-coded one.
    "bot_username": str,
}


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _coerce(key: str, value: str, where: str, target: type) -> object:
    """Turn a scalar into `target`, or fail naming the exact line and key."""
    text = _unquote(value)
    if target is str:
        return text
    if not text:
        raise ValueError(f"{where}: `{key}` needs a number, got an empty value")
    try:
        return int(text) if target is int else float(text)
    except ValueError as exc:
        raise ValueError(f"{where}: `{key}` needs a number, got {text!r}") from exc


def load_sources(path: Path) -> tuple[list[Source], dict]:
    """Read the source list *and* the file-level knobs.

    Returns `(sources, settings)`. Two values, not one, because the caller hands
    both to `Pipeline` and `create_app` — both read `canary_token`,
    `protocol_reliability`, `source_pass_rate` and `base_url` out of the same
    mapping they read `sources` from, and returning only the list is what made
    every one of those keys silently fall back to a default.

    Minimal parser: no PyYAML dependency. Accepts a JSON array, a JSON object
    with a `sources` key, or YAML in the simple ``- url:`` / ``  include: []``
    shape this project uses. The one piece of YAML semantics that *matters* here
    is indentation: it is what separates a key inside a `- url:` entry from a
    file-level knob, and the previous reader ignored it, so `source_pass_rate:`
    sitting after the list was folded into the last source and exploded inside
    `Source(**current)`.
    """
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()

    if stripped.startswith("[") or stripped.startswith("{"):
        import json

        data = json.loads(text)
        if isinstance(data, dict):
            return _build_sources(data.pop("sources", None) or [], path), data
        return _build_sources(data, path), {}

    sources: list[Source] = []
    settings: dict = {}
    current: dict = {}
    #: The `- ` indentation that starts a source entry. A `- ` deeper than the
    #: key it follows is that key's value (a block list), not a new entry.
    block_key: str | None = None
    block_indent = -1

    def flush() -> None:
        """Close the entry being accumulated and start a fresh one."""
        nonlocal current
        if current:
            unknown = sorted(set(current) - set(SOURCE_FIELDS))
            if unknown:
                raise ValueError(
                    f"{path}: unknown source field(s) {', '.join(unknown)}; "
                    f"expected one of {', '.join(SOURCE_FIELDS)}"
                )
            sources.append(Source(**current))
        current = {}

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        where = f"{path}:{lineno}"
        indent = len(raw_line) - len(raw_line.lstrip())
        line = raw_line.strip()

        # A column-0 key is file-level, full stop. This is the whole fix.
        if indent == 0 and not line.startswith("-"):
            flush()
            if ":" not in line:
                raise ValueError(f"{where}: expected `key: value`, got {line!r}")
            name, _, value = line.partition(":")
            name = name.strip()
            if not name:
                raise ValueError(f"{where}: missing key name")
            value = value.strip()
            if name == "sources":
                if value:
                    raise ValueError(f"{where}: `sources:` is a list; remove {value!r}")
                block_key = None
                continue
            if name not in FILE_SETTINGS:
                raise ValueError(
                    f"{where}: unknown setting `{name}`; expected one of "
                    f"{', '.join(sorted(FILE_SETTINGS))}"
                )
            settings[name] = _coerce(name, value, where, FILE_SETTINGS[name])
            block_key = None
            continue

        if line.startswith("-"):
            item = line[1:].strip()
            if block_key is not None and indent > block_indent:
                # A block list under `include:`/`exclude:`, not a new entry.
                if item:
                    current.setdefault(block_key, [])
                    if isinstance(current[block_key], list):
                        current[block_key].append(_unquote(item))
                continue
            flush()
            block_key = None
            line = item
            if not line:
                continue  # `-` alone: the fields follow on the next lines
            indent += 2

        if ":" not in line:
            raise ValueError(f"{where}: expected `key: value`, got {line!r}")
        name, _, value = line.partition(":")
        name = name.strip()
        if name not in SOURCE_FIELDS:
            raise ValueError(
                f"{where}: unknown source field `{name}`; expected one of "
                f"{', '.join(SOURCE_FIELDS)}"
            )
        value = _unquote(value)
        if value:
            if name in ("include", "exclude"):
                current[name] = _split_list(value)
            elif value.lower() in ("true", "false"):
                current[name] = value.lower() == "true"
            else:
                current[name] = value
            block_key = None
        else:
            # An empty value opens a block list: the items follow, indented.
            block_key = name
            block_indent = indent

    flush()
    return sources, settings


def _split_list(value: str) -> tuple[str, ...]:
    """`a, b`, `[a, b]` and a bare `a` all mean the same list."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _build_sources(entries, path: Path) -> list[Source]:
    """Build `Source` objects from deserialised JSON, validating field names."""
    if not isinstance(entries, list):
        raise ValueError(f"{path}: `sources` must be a list, got {type(entries).__name__}")
    built = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            built.append(Source(url=str(entry)))
            continue
        unknown = sorted(set(entry) - set(SOURCE_FIELDS))
        if unknown:
            raise ValueError(
                f"{path}: sources[{index}] has unknown field(s) "
                f"{', '.join(unknown)}; expected one of {', '.join(SOURCE_FIELDS)}"
            )
        built.append(Source(**entry))
    return built
