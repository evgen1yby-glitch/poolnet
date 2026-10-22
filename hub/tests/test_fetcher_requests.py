"""`Fetcher` tests: conditional requests, round accounting, the circuit breaker.

`tests/test_fetcher.py` shares this file's subject but covers only
`load_sources`, the config parser. That leaves the fetcher itself with no test
at all — which is how it ended up promising three behaviours in its docstring
that did not exist:

* "an `ETag`/`If-None-Match` 304 ... lets us skip parsing entirely", when a 304
  returned an *empty body* and `run_once` builds its whole pool from fetched
  bodies;
* "a source returning 20 consecutive empty rounds is disabled", when
  `EMPTY_ROUND_LIMIT` was declared and never read;
* "new sources are quarantined below (contribution cap until 10 rounds)", when
  nothing in the code knew what quarantine was.

Every test here is written so that deleting the code it targets makes it fail.
That discipline is the point, not decoration: the previous suite's negative
assertions kept passing because a *second* mechanism produced the same
observation (a 404 that both a traversal guard and a missing file can cause). A
fixture that only one mechanism can explain is what distinguishes "this code
works" from "this test cannot tell".

Two fixture notes:

* The injected client has the shape `(url, headers)` and returns
  `(body, status, headers)`. It is a coroutine function, not a plain function,
  and headers are lower-cased by convention — `fetch_one` reads `etag` and
  `retry-after`, matching what `urllib`'s `HTTPMessage` preserves from
  `email.message`.
* `time.sleep` is patched, never `asyncio.sleep`, so the retry paths run in
  microseconds and assertions about *which* delay was chosen are still exact.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.fetcher import (  # noqa: E402
    EMPTY_ROUND_LIMIT,
    QUARANTINE_CAP,
    QUARANTINE_ROUNDS,
    Fetcher,
    Source,
    _retry_after_seconds,
)

# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


class RecordingClient:
    """Stands in for HTTP, recording what was asked and choosing the answer.

    The answer is a list of `(status, headers, body)` consumed one entry per
    call, so a test can script "200 then 304" without worrying about ordering.
    An exhausted list repeats its last entry, which is what a host that keeps
    answering 503 looks like.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, url: str, headers: dict):
        self.calls.append((url, dict(headers)))
        if not self.answers:
            return "", 503, {}
        if len(self.answers) > 1:
            status, extra, body = self.answers.pop(0)
        else:
            status, extra, body = self.answers[0]
        return body, status, extra


def _source(url="https://example.invalid/config.txt", name="example"):
    return Source(url=url, name=name)


@pytest.fixture
def no_sleep(monkeypatch):
    """Make the retry backoff free without touching the code's logic.

    Wall-clock sleeps are the one thing a retry test cannot afford; replacing
    `asyncio.sleep` would also hide *whether* a backoff was taken at all, since
    a patched no-op sleeps exactly as "happily" as an honest zero-second sleep.
    Recording the requested delay instead keeps both facts: the test runs fast
    *and* it can assert what the code decided to wait.
    """
    delays: list[float] = []

    async def _record(seconds: float):
        delays.append(seconds)

    monkeypatch.setattr("hub.fetcher.asyncio.sleep", _record)
    return delays


# --------------------------------------------------------------------------- #
# conditional requests
# --------------------------------------------------------------------------- #


async def test_a_304_returns_the_cached_body_rather_than_an_empty_one():
    """The whole reason the cache column exists.

    A 304 means "unchanged", and the copy we already hold *is* the current
    content of that URL. If it is thrown away, the round sees a source that
    produced nothing — and `pipeline.run_once` builds its node pool from
    fetched bodies only, so every unchanged source would publish an empty
    generation. The observable that discriminates is the *body*: an empty body
    is also what a genuinely dead source returns, so asserting on the body is
    what pins this behaviour rather than the transport.
    """
    client = RecordingClient([(304, {}, "")])
    fetcher = Fetcher(
        [_source()],
        client=client,
        states={"https://example.invalid/config.txt": {"etag": '"v1"',
                                                        "body": "vless://cached#x"}},
    )
    items, stats = await fetcher.fetch_all()

    assert len(items) == 1, items
    assert items[0].not_modified is True
    assert items[0].body == "vless://cached#x", (
        "a 304 must yield the cached body; an empty one reads as a dead source"
    )
    assert stats.not_modified == 1
    # The ETag we cached is what is sent, or the host answers 200 every round
    # and the conditional request is decorative.
    assert client.calls[0][1].get("If-None-Match") == '"v1"'


async def test_a_304_with_no_cached_body_yields_an_empty_body_not_an_error():
    """Cold start, or the first round after the cache column is added.

    There is nothing to reuse, so the honest answer is an empty body — but the
    run must survive it. The earlier code returned `RawItem(..., body="",
    not_modified=True)` and the pipeline treated that as a normal source that
    simply had nothing today, which is what this pins.
    """
    client = RecordingClient([(304, {}, "")])
    fetcher = Fetcher([_source()], client=client)
    items, stats = await fetcher.fetch_all()

    assert len(items) == 1
    assert items[0].body == ""
    assert items[0].not_modified is True
    assert stats.not_modified == 1
    assert stats.failed == 0, "a 304 is not a failure"


async def test_the_cached_body_is_the_fetched_body_not_the_adapted_one():
    """`fetch_one` caches *before* the adapter runs.

    The pipeline adapts the body itself, so caching an adapted body would mean
    that fixing an adapter still serves the pre-fix content on a 304 for one
    more round. The observable is which form the 304 round returns.
    """
    url = "https://example.invalid/openvpn.csv"
    states = {url: {"etag": '"v1"', "body": "raw,openvpn,payload"}}
    client = RecordingClient([(304, {}, "")])
    fetcher = Fetcher([_source(url=url)], client=client, states=states)
    items, _stats = await fetcher.fetch_all()

    assert items[0].body == "raw,openvpn,payload"


async def test_a_fresh_200_stores_the_etag_and_body_for_the_next_round():
    """Without this the conditional request never happens again.

    `Fetcher` is destroyed at the end of every `hub run`, so the only way the
    next process can send `If-None-Match` is if the body and tag were put into
    `states` and handed back. Asserting on `state(url)` covers it directly;
    asserting on the next request's headers would also pass if the *caller*
    persisted it, and that is the pipeline's job, not this test's.
    """
    url = "https://example.invalid/config.txt"
    client = RecordingClient([(200, {"etag": '"v2"'}, "vless://fresh#x")])
    fetcher = Fetcher([_source(url=url)], client=client)
    items, stats = await fetcher.fetch_all()

    assert items[0].body == "vless://fresh#x"
    assert stats.fetched == 1
    state = fetcher.state(url)
    assert state["etag"] == '"v2"'
    assert state["body"] == "vless://fresh#x"


# --------------------------------------------------------------------------- #
# round accounting and the circuit breaker
# --------------------------------------------------------------------------- #


async def test_a_non_empty_round_clears_the_empty_round_streak():
    """The limit is about *consecutive* empties.

    A source alternating empty and non-empty is a different problem from one
    that is permanently dead, and treating them the same disables healthy
    sources on a bad cadence. The streak counter resetting is the observable.
    """
    url = "https://example.invalid/config.txt"
    fetcher = Fetcher(
        [_source(url=url)],
        client=RecordingClient([(200, {}, "vless://ok#x")]),
        states={url: {"empty_rounds": 7, "rounds": 9}},
    )
    fetcher.end_round(_source(url=url), 3)
    assert fetcher.state(url)["empty_rounds"] == 0


async def test_an_empty_round_advances_the_streak_and_the_round_count():
    """`rounds` counts *completed* rounds, once each.

    Pinned with `begin_round` → `end_round(0)` because that was the double
    count: bumping on both start and close made one round register as two, so a
    source reached `QUARANTINE_ROUNDS` of "history" in half the rounds and the
    quarantine cap lifted early. A source that has genuinely completed one
    empty round shows `rounds: 1` — the observable that separates the two.
    """
    url = "https://example.invalid/config.txt"
    fetcher = Fetcher([_source(url=url)])
    fetcher.begin_round(_source(url=url))
    fetcher.end_round(_source(url=url), 0)
    assert fetcher.state(url)["empty_rounds"] == 1
    assert fetcher.state(url)["rounds"] == 1


async def test_a_successful_round_advances_the_round_count_too():
    """History is rounds *completed*, not rounds failed.

    Otherwise a healthy source stays quarantined forever and its contribution
    is capped indefinitely, which is the opposite failure from the one the cap
    exists to prevent.
    """
    url = "https://example.invalid/config.txt"
    fetcher = Fetcher([_source(url=url)])
    fetcher.end_round(_source(url=url), 12)
    assert fetcher.state(url)["rounds"] == 1
    assert fetcher.state(url)["empty_rounds"] == 0
    assert fetcher.state(url)["last_ok"], "a productive round records when it worked"


async def test_the_circuit_breaker_disables_at_the_limit_and_not_before():
    """`EMPTY_ROUND_LIMIT` was declared and never read; this pins that it is.

    Both halves matter. Disabling *before* the limit kills a source that needed
    one more good round; not disabling *at* the limit leaves a permanently dead
    URL being fetched forever, which is the documented promise.

    The discriminating fixture is the streak set to exactly `LIMIT - 1` plus one
    empty round: the source is at the boundary, so the only way to reach
    "disabled" is the limit check itself. A source at streak 0 or 5 would pass
    with an off-by-one implementation.
    """
    url = "https://example.invalid/config.txt"
    fetcher = Fetcher([_source(url=url)])
    fetcher.state(url)["empty_rounds"] = EMPTY_ROUND_LIMIT - 1

    fetcher.end_round(_source(url=url), 0)

    assert fetcher.state(url)["empty_rounds"] == EMPTY_ROUND_LIMIT
    assert fetcher.state(url)["enabled"] == 0, (
        "a source failing EMPTY_ROUND_LIMIT rounds in a row must be disabled"
    )
    assert fetcher.is_disabled(url)
    assert url in fetcher.newly_disabled

    # One round short of the limit leaves it enabled.
    fetcher2 = Fetcher([_source(url=url)])
    fetcher2.state(url)["empty_rounds"] = EMPTY_ROUND_LIMIT - 2
    fetcher2.end_round(_source(url=url), 0)
    assert fetcher2.state(url)["enabled"] == 1, "disabled below the limit"


async def test_a_source_disabled_by_the_breaker_is_not_fetched_next_round():
    """The breaker has to survive the process boundary to mean anything.

    `enabled: 0` in the loaded state is how a disabled source stays disabled.
    The observable is that the client is never called, and that the source is
    named in `stats.disabled` rather than vanishing silently — an operator
    needs to see *which* sources the pool stopped trusting.
    """
    url = "https://example.invalid/config.txt"
    client = RecordingClient([(200, {}, "vless://never#x")])
    fetcher = Fetcher(
        [_source(url=url)], client=client, states={url: {"enabled": 0}}
    )
    items, stats = await fetcher.fetch_all()

    assert client.calls == [], "a disabled source must not be fetched"
    assert items == []
    assert stats.disabled == ["example"]


async def test_the_audit_can_refetch_a_source_the_breaker_disabled():
    """`scripts/audit_sources.py` re-verifies sources on purpose.

    Re-checking a URL the breaker stopped trusting is the question the audit
    exists to answer, so `skip_disabled=False` must fetch it. This is the mirror
    of the previous test: the same `enabled: 0` state, the opposite request.
    """
    url = "https://example.invalid/config.txt"
    client = RecordingClient([(200, {}, "vless://alive#x")])
    fetcher = Fetcher(
        [_source(url=url)], client=client, states={url: {"enabled": 0}}
    )
    items, _stats = await fetcher.fetch_all(skip_disabled=False)

    assert len(client.calls) == 1, "the audit must be able to refetch"
    assert items[0].body == "vless://alive#x"


async def test_a_source_disabled_in_the_yaml_is_never_fetched():
    """`enabled: false` is the operator's override and outranks the DB."""
    disabled = Source(url="https://example.invalid/off.txt", name="off", enabled=False)
    client = RecordingClient([(200, {}, "vless://x#y")])
    fetcher = Fetcher([disabled], client=client)
    items, stats = await fetcher.fetch_all()

    assert client.calls == []
    assert stats.disabled == ["off"]


# --------------------------------------------------------------------------- #
# quarantine
# --------------------------------------------------------------------------- #


async def test_a_brand_new_source_is_capped():
    """Quarantine: a source with no track record cannot dominate the pool.

    One unvetted URL listing ten thousand dead nodes must not set the whole
    pool's character on its first day, so it is capped until it has
    `QUARANTINE_ROUNDS` rounds of history. `rounds == 0` is the discriminating
    fixture: a source at `QUARANTINE_ROUNDS` would pass with the cap removed
    accidentally, and one at any non-zero value would pass if only
    `is None` were checked.
    """
    url = "https://example.invalid/new.txt"
    fetcher = Fetcher([_source(url=url)], states={url: {"rounds": 0}})
    cap = fetcher.quarantine_cap(url)
    assert cap == QUARANTINE_CAP, "a new source must be capped"
    assert cap is not None


async def test_a_source_with_history_is_uncapped():
    """And once it has the history, the cap lifts entirely."""
    url = "https://example.invalid/old.txt"
    fetcher = Fetcher(
        [_source(url=url)], states={url: {"rounds": QUARANTINE_ROUNDS}}
    )
    assert fetcher.quarantine_cap(url) is None


async def test_a_source_one_round_short_of_trust_is_still_capped():
    """The boundary, so the comparison cannot be off by one."""
    url = "https://example.invalid/edge.txt"
    fetcher = Fetcher(
        [_source(url=url)], states={url: {"rounds": QUARANTINE_ROUNDS - 1}}
    )
    assert fetcher.quarantine_cap(url) == QUARANTINE_CAP


# --------------------------------------------------------------------------- #
# Retry-After
# --------------------------------------------------------------------------- #


def test_retry_after_seconds_parses_delta_seconds():
    assert _retry_after_seconds("120") == 120.0
    assert _retry_after_seconds("0") == 0.0


def test_retry_after_http_date_is_converted_relative_to_now():
    """Both RFC 7231 forms are legal, and honouring only one looks implemented."""
    now = 1_700_000_000.0
    import datetime as _dt

    when = _dt.datetime.fromtimestamp(now + 90, _dt.timezone.utc)
    stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert _retry_after_seconds(stamp, now=now) == pytest.approx(90.0, abs=2)


def test_retry_after_in_the_past_sleeps_nothing():
    """A stale instruction is clamped to zero, not made negative."""
    assert _retry_after_seconds("Wed, 21 Oct 2020 07:28:00 GMT", now=1_700_000_000.0) == 0.0


def test_retry_after_unparseable_returns_none_rather_than_guessing():
    """"I could not read this" and "wait zero seconds" are different claims.

    Returning 0 would mean hammering a host that just asked us to slow down,
    which is the specific failure the header exists to prevent. The caller
    falls back to its own backoff on `None`.
    """
    assert _retry_after_seconds("soon") is None
    assert _retry_after_seconds("") is None
    assert _retry_after_seconds("   ") is None


async def test_a_429_with_retry_after_is_waited_out_for_that_long(no_sleep):
    """The documented promise, and the reason `no_sleep` records rather than no-ops.

    A 429 that is retried on a fixed 10/20/30s schedule is the same as ignoring
    the header one attempt later. Asserting on the *delay* is what makes this a
    real test, and it is why the sleep is patched with a recorder.
    """
    client = RecordingClient([(429, {"retry-after": "300"}, ""), (200, {}, "vless://ok#x")])
    fetcher = Fetcher([_source()], client=client, retries=2, backoff=1.0)
    items, stats = await fetcher.fetch_all()

    assert no_sleep == [300.0], f"expected the Retry-After delay, got {no_sleep}"
    assert len(items) == 1, "the call is retried after the wait"
    assert stats.attempted == 2


async def test_a_429_without_retry_after_falls_back_to_backoff(no_sleep):
    """A rate limit with no usable header still backs off — but on our own terms.

    Without this, `_retry_after_seconds` returning `None` would be read as "wait
    zero", and the source would be hammered.
    """
    client = RecordingClient([(429, {}, ""), (200, {}, "vless://ok#x")])
    fetcher = Fetcher([_source()], client=client, retries=2, backoff=1.0)
    items, _stats = await fetcher.fetch_all()

    assert no_sleep == [1.0 * 1], no_sleep
    assert len(items) == 1


async def test_a_503_with_retry_after_is_also_honoured(no_sleep):
    """503 carries `Retry-After` too, and it means the same thing."""
    client = RecordingClient([(503, {"retry-after": "60"}, ""), (200, {}, "x")])
    fetcher = Fetcher([_source()], client=client, retries=2, backoff=1.0)
    _items, _stats = await fetcher.fetch_all()
    assert no_sleep == [60.0], no_sleep


async def test_exhausting_retries_records_a_failure_not_an_exception(no_sleep):
    """One dead source must not take the run down with it.

    The observable is `stats.failed` plus the error label, because returning
    `None` is also what "successfully fetched nothing" looks like from the
    caller's side.
    """
    client = RecordingClient([(500, {}, "boom")])
    fetcher = Fetcher([_source()], client=client, retries=2, backoff=1.0)
    items, stats = await fetcher.fetch_all()

    assert items == []
    assert stats.failed == 1
    # Two attempts produced two recorded HTTP errors: `attempted` counts
    # requests issued, not sources tried, so this is 2 and not 1.
    assert stats.errors.get("http_500") == 2
    assert stats.attempted == 2
    assert stats.errors.get("exhausted") == 1


async def test_exhausting_retries_counts_an_empty_round():
    """A source we could not reach is a source that yielded nothing.

    This is what feeds the circuit breaker, so it is asserted separately from
    the stats: the breaker is driven by `end_round`, and a transport failure
    that did not also count as an empty round would never trip it.
    """
    client = RecordingClient([(500, {}, "boom")])
    fetcher = Fetcher([_source()], client=client, retries=1, backoff=0.0)
    await fetcher.fetch_all()

    url = "https://example.invalid/config.txt"
    assert fetcher.state(url)["empty_rounds"] == 1
