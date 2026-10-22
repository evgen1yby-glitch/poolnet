"""`scripts/audit_sources.py` must report what the pipeline will actually ingest.

The audit's whole value is that it answers "what does this source contribute?"
in the same terms `run_once` uses. Auditing without the per-source
`include`/`exclude` filters breaks that, and breaks it in the direction an
operator cannot see: a source declaring `include: ['^vless']` on a body that is
entirely trojan reports **5 nodes OK** here and **0 nodes** in production. The
audit exists to catch exactly that inversion — "the pool is thinner than the
sources say" — so a filter-blind audit would certify the very discrepancy it was
written to detect.

The fix was to call `Pipeline._filter_body` rather than to reimplement the
rules, and this file also pins *that* decision: a second copy of the filter
logic is a second place for it to be wrong, and the only way to know the audit
still agrees with the pipeline is to test them against each other.

The tests drive `audit_one` directly with the fetch client replaced, so nothing
here touches the network. That is not a convenience: the audit is a read-only
inspection tool, and a test that fetched 13 real URLs to check a regex would be
both slow and fragile.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hub import fetcher  # noqa: E402
from hub.parser import parse_many  # noqa: E402

import audit_sources  # noqa: E402

#: Five vless share URIs, all of them containing `example` and none containing
#: `trojan` — the shape that makes the two filter directions distinguishable.
BODY = "\n".join(
    f"vless://11111111-2222-3333-4444-555555555555@k{i}.example.com:443"
    f"?security=reality&sni=a#k{i}"
    for i in range(5)
)


@pytest.fixture
def offline_fetcher(monkeypatch):
    """`Fetcher` that answers every request with a canned body and dials nothing.

    Patched at `Fetcher.__init__` rather than at the module's HTTP helper,
    because `audit_one` constructs its own `Fetcher` and the seam the pipeline
    uses is the injected `client` — the same seam, so what is exercised here is
    the same code path as `run_once`.

    The body is read through `_BODY[0]` so a test can substitute its own by
    overriding the module-level box, which keeps the patch in exactly one place.
    A second copy of this patch per test is how a suite drifts into testing a
    path nothing in production takes.
    """
    original = fetcher.Fetcher.__init__
    current = _BODY

    async def _client(url, headers):  # noqa: ANN001
        return current[0], 200, {}

    def patched(self, sources, **kwargs):
        original(self, sources, **kwargs)
        self._client = _client

    monkeypatch.setattr(fetcher.Fetcher, "__init__", patched)
    return fetcher


#: The body the offline fetcher serves. A one-element list so a test can
#: substitute a different body without re-patching `Fetcher`.
_BODY = [BODY]


@pytest.fixture(autouse=True)
def _restore_body():
    """Put the default body back after every test.

    A test that substitutes its own body writes into a shared box, and without
    this the substitution leaks: the next test asserts against `BODY` while the
    fetcher serves something else, and the failure names a count that has
    nothing to do with the logic under test. One autouse fixture is cheaper than
    debugging that.
    """
    yield
    _BODY[0] = BODY


async def _audit(**source_over):
    source = fetcher.Source(url="https://example.test/x", name="fixture", **source_over)
    return await audit_sources.audit_one(source, 5.0, 1)


async def test_the_audit_reports_every_node_when_a_source_declares_no_filters(
    offline_fetcher,
):
    """The baseline: no filters means no filtering.

    Without this, `nodes == 4` in the filter test below has nothing to be
    relative to — the same number would also appear if the parser only ever
    produced 4 nodes from this body.
    """
    record = await _audit()
    assert record["nodes"] == 5, record
    assert record["protocols"] == {"vless": 5}, record
    assert "filtered" not in record, "a source with no filters recorded a filtering"


async def test_an_include_that_rejects_everything_is_reported_as_zero(
    offline_fetcher,
):
    """The inversion this file exists for.

    `include: ['^trojan']` on an all-vless body means the pipeline contributes
    nothing. Before the audit consulted the filters it reported 5 nodes — a
    source that looks healthy here and is empty in production, which is the
    discrepancy the audit is supposed to surface.
    """
    record = await _audit(include=("^trojan",))
    assert record["nodes"] == 0, record
    assert record["filtered"] == {"before": 5, "after": 0}, record


async def test_an_exclude_that_rejects_everything_is_reported_as_zero(
    offline_fetcher,
):
    """The same guard from the other direction.

    Separate assertion because `include` and `exclude` are separate branches in
    `_filter_body`, and a run that deleted only one of them would look identical
    to a test that only checked the other.
    """
    record = await _audit(exclude=("example",))
    assert record["nodes"] == 0, record


async def test_an_exclude_that_matches_nothing_changes_nothing(offline_fetcher):
    """A filter that drops nothing must not be recorded as having filtered.

    `filtered` is present exactly when the body changed, because it is the
    operator's cue that the numbers below are *after* the filters. Recording it
    unconditionally would mark every source as filtered and make the field
    meaningless.
    """
    record = await _audit(exclude=("trojan",))
    assert record["nodes"] == 5, record
    assert "filtered" not in record, record


async def test_both_filters_together_narrow_to_what_the_pipeline_would_keep(
    offline_fetcher,
):
    """The two filters combined, matching `run_once`'s documented order.

    `include` first, then `exclude` removes from what survived. Four of five
    nodes survive `exclude=('k4',)`, which is only true if the include ran too —
    an unfiltered body of 5 minus 1 is 4, so the include is what makes the pair
    discriminating rather than redundant.
    """
    record = await _audit(include=("^vless",), exclude=("k4",))
    assert record["nodes"] == 4, record
    assert record["filtered"] == {"before": 5, "after": 4}, record


async def test_an_emptied_body_says_the_filters_did_it_not_the_source(
    offline_fetcher,
):
    """Zero nodes must not read as "the URL serves an index page".

    The URL is alive and served five share URIs. The operator's own `exclude`
    is what discarded all of them, and a note blaming the body's content sends
    them to look for a problem at a host that has none. This is the note that
    distinguishes "fix your regex" from "find a new source".

    Pinned on the exact sentence, not on `"filters" in note`: the partial-note
    branch below it also contains the word "filters" ("5 lines fetched, 0 after
    filters"), so a substring assertion is satisfied by a different code path
    and proves neither. An over-determined observation is not evidence, which is
    why this names the sentinel that only the emptied-body branch produces.
    """
    record = await _audit(exclude=("example",))
    assert "every line was removed" in record["note"], record
    assert "index page" not in record["note"], record


async def test_a_partially_filtered_body_records_how_many_survived(offline_fetcher):
    """The other fold: some lines survive, so there is no note to write.

    Asserted on the `filtered` ledger rather than on `note`, and that is the
    point: the note is only written when nothing survives, because "0 nodes" with
    a note saying so is the case that needs explaining. A partially filtered
    source has a positive node count, which is self-explanatory, and the ledger
    is where the numbers live.

    A test that looked for a note here would be asserting on a field the code
    correctly leaves empty — and would then need the code to write a redundant
    one just to pass.
    """
    record = await _audit(include=("^vless",), exclude=("k4",))
    assert record["nodes"] == 4, record
    assert record["filtered"] == {"before": 5, "after": 4}, record
    assert record["note"] == "", "a productive source does not need a note"


async def test_a_body_that_survives_the_filters_and_still_parses_to_nothing_says_so(
    offline_fetcher,
):
    """The fold between "the filters emptied it" and "it is an index page".

    A line can pass the filters and still fail to parse: `not-a-uri` contains
    nothing any include/exclude pattern would drop, and nothing the parser
    accepts either. The body is non-empty *after* filtering, so the
    emptied-body note must not fire — and `nodes == 0` with no note at all would
    leave the operator guessing.

    This is the case that pins both note branches at once, because their
    sentinels differ only in `after == 0` versus `after < before`: if the
    branches were merged, or if the comparison were inverted, this is the input
    that separates them.
    """
    # One line that matches the include pattern and fails to parse, so the body
    # is non-empty *after* filtering while still yielding no nodes.
    _BODY[0] = "not-a-uri"
    record = await _audit(include=("^not-a-uri",))
    assert record["nodes"] == 0, record
    # No `filtered` ledger: the filters kept the only line there was, so the
    # body before and after is the same string and there is nothing to record.
    assert "filtered" not in record, record
    assert "every line was removed" not in record["note"], record
    assert "index page" in record["note"], record


async def test_a_body_thinned_by_filters_and_still_empty_says_the_filters_did_it(
    offline_fetcher,
):
    """The fold the other note test cannot reach: `after` in between.

    Both earlier notes need `nodes == 0`, and they differ only in what the
    filters left behind:

    * `after == 0` — the filters emptied the body, nothing survived to parse;
    * `after == before` — the filters kept everything, and what survived is
      unparseable, so the body itself is the problem.

    This is the remaining case: the filters *thinned* a body whose remainder is
    unparseable. The body is non-empty after filtering, so the emptied-body
    branch must not fire — and the partial branch must, because "0 nodes" from a
    body that used to have lines is the situation where an operator looks at the
    source URL rather than at their own regex.

    Asserted on the exact sentence, since the two branches' texts share the word
    "filters" and a substring check would be satisfied by either.
    """
    # `keep-this` survives both filters; `not-a-uri` does not; the survivor is
    # still unparseable, so the round yields nothing.
    _BODY[0] = "\n".join(["keep-this", "not-a-uri"])
    record = await _audit(exclude=("not-a-uri",))
    assert record["nodes"] == 0, record
    assert record["filtered"] == {"before": 2, "after": 1}, record
    assert "2 lines fetched" in record["note"], record
    assert "1 after filters" in record["note"], record
    assert "every line was removed" not in record["note"], record


async def test_the_audit_agrees_with_the_pipeline_on_the_same_body(tmp_path):
    """The real contract: same source, same body, same node count.

    This is the test that would catch a fork. If `audit_sources` ever grows its
    own copy of the filter rules, or `Pipeline._filter_body` changes shape the
    way the first version of the helper assumed, this is the assertion that
    goes red — it runs both and compares.
    """
    from hub.pipeline import Pipeline

    source = fetcher.Source(
        url="https://example.test/x",
        name="fixture",
        include=("^vless",),
        exclude=("k4",),
    )
    pipeline = Pipeline(root=tmp_path, sources={"sources": [source]})
    pipeline_body = pipeline._filter_body(BODY, pipeline._source_filters("include"),
                                          pipeline._source_filters("exclude"), source.key)
    pipeline_nodes, _errors = parse_many(pipeline_body, source=source.key)

    audit_body = audit_sources._filter_body_for(source, BODY)
    audit_nodes, _errors = parse_many(audit_body, source=source.key)

    assert len(pipeline_nodes) == len(audit_nodes) == 4, (pipeline_nodes, audit_nodes)
