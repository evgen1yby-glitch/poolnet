#!/usr/bin/env python3
"""Re-verify every source in `config/sources.yaml` and report what it yields.

A source list rots silently. The URLs look plausible forever — a repo is
renamed, a maintainer restructures `Splitted-By-Protocol/` into `split/`, a README
stops listing the file it used to — and the run report records a successful fetch
that produced nothing. The pool gets thinner and nothing says why.

This script closes that loop. For each source it fetches the real body through
the project's own `Fetcher` (not a bespoke HTTP path, so the audit exercises the
same timeout, retry and User-Agent the pipeline uses), runs it through the same
`parse_many` the pipeline uses, and prints the node count per protocol. A source
that yields zero nodes is reported as `DEAD`, with the reason — adapter refusal,
HTTP failure, or a body that parsed to nothing — which is the difference between
"the URL moved", "the shape changed", and "the URL serves an index page".

    python3 scripts/audit_sources.py                 # every source in the config
    python3 scripts/audit_sources.py --only Epodonios
    python3 scripts/audit_sources.py --json out.json

Exit status is 1 if any source yields zero nodes and 0 otherwise, so this is
usable from a cron job or a CI step that should fail when the pool empties.

No node is ever dialled and no config is ever written: this is a read-only
inspection of the sources, and it deliberately does not construct a
`CoreDriver` or touch `data/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hub.fetcher import Fetcher, load_sources  # noqa: E402
from hub.parser import parse_many  # noqa: E402
from hub.adapters import adapt  # noqa: E402


def _filter_body_for(source, body: str) -> str:
    """`Pipeline._filter_body` for one source, reusing the pipeline's own code.

    Imported rather than reimplemented: a second copy of the filter rules would
    be a second place for them to be wrong, and the audit's whole value is that
    it reports what the pipeline will actually ingest.

    The shape matters: `_filter_body` looks its patterns up as
    `{source name: compiled patterns}`, which is how `run_once` builds them in
    `_source_filters`. Passing the bare tuple here reads as "this source
    declared include patterns for a source called `key`", and every lookup
    misses — a filter that silently does nothing, in the one script whose job is
    to report what will actually be ingested.
    """
    import re

    from hub.pipeline import Pipeline

    compiled = {}
    for attr in ("include", "exclude"):
        patterns = tuple(getattr(source, attr) or ())
        if patterns:
            compiled[attr] = {source.key: tuple(re.compile(p) for p in patterns)}
    return Pipeline._filter_body(
        body, compiled.get("include", {}), compiled.get("exclude", {}), source.key
    )


async def audit_one(source, timeout: float, retries: int) -> dict:
    """One source: fetch, adapt, parse, count.

    A failure at any stage is a finding rather than an exception: "the source
    raises" is exactly what an operator needs to know, and it must not abort the
    audit of the remaining sources.
    """
    fetcher = Fetcher([source], timeout=timeout, retries=retries)
    record = {"name": source.key, "url": source.url, "kind": source.kind or "",
              "bytes": 0, "nodes": 0, "protocols": {}, "note": ""}
    try:
        items, stats = await fetcher.fetch_all()
    except Exception as exc:  # noqa: BLE001 - the audit must survive one bad source
        record["note"] = f"fetch raised {type(exc).__name__}: {exc}"
        return record

    errors = dict(getattr(stats, "errors", {}) or {}) if stats is not None else {}
    if errors:
        record["note"] = "; ".join(f"{k}={v}" for k, v in errors.items())
    if not items:
        # No item at all means the fetch failed or 304'd with nothing cached.
        # `bytes`/`nodes` stay 0 and the note carries the reason, so the verdict
        # is DEAD rather than OK-with-nothing — which is the whole point.
        if not record["note"]:
            record["note"] = "no body returned (HTTP error or 304 with no cache)"
        return record

    item = items[0]
    record["bytes"] = len(item.body.encode("utf-8", "replace"))
    if item.not_modified:
        record["note"] = "304 not modified (ETag hit; body is the cached copy)"

    # The adapter's *refusal* is a distinct outcome from a body that parses to
    # nothing. A source that declares `kind: vpngate` and returns CSV we cannot
    # turn into share URIs should say so, not silently count as zero nodes,
    # because "the adapter declined" and "the URL is dead" are different fixes.
    adapted = adapt(source.kind or "", item.body or "")
    if not adapted.ok:
        record["note"] = f"adapter refused: {adapted.reason}"
        return record
    try:
        body = adapted.text
    except Exception as exc:  # noqa: BLE001
        record["note"] = f"adapter raised {type(exc).__name__}: {exc}"
        return record

    # The per-source filters run *before* the parse in `run_once`, and auditing
    # without them reports a node count the pipeline will never see. A source
    # declaring `include: ['^vless']` whose body is all trojan is OK by this
    # script's numbers and DEAD in production — the exact inversion the audit
    # exists to prevent. `_filter_body` is the pipeline's own helper, so the two
    # cannot drift: there is one implementation of "what this source contributes".
    filtered = _filter_body_for(source, body)
    if filtered != body:
        record["filtered"] = {
            "before": len((body or "").splitlines()),
            "after": len(filtered.splitlines()),
        }

    try:
        nodes, parse_errors = parse_many(filtered, source=source.key)
    except Exception as exc:  # noqa: BLE001
        record["note"] = f"parse raised {type(exc).__name__}: {exc}"
        return record

    record["nodes"] = len(nodes)
    record["protocols"] = dict(Counter(n.protocol.value for n in nodes).most_common())
    if parse_errors:
        record["parse_errors"] = len(parse_errors)
    if not nodes and not record["note"]:
        # An emptied body means the *filters* removed everything, which is a
        # different finding from an index page: the URL is alive and served share
        # URIs, and the operator's own exclude pattern is what discarded them.
        # Ditto a body that arrived non-empty and left empty between the fetch
        # and the note below — same cause, reached by a different route.
        if "filtered" in record and record["filtered"]["after"] == 0:
            record["note"] = (
                "every line was removed by this source's include/exclude "
                f"filters ({record['filtered']['before']} lines fetched)"
            )
        elif "filtered" in record and record["filtered"]["after"] < record["filtered"]["before"]:
            record["note"] = (
                f"{record['filtered']['before']} lines fetched, "
                f"{record['filtered']['after']} after filters"
            )
        else:
            record["note"] = "body parsed but contained no share URIs (index page?)"
    return record


async def run(args) -> int:
    sources, _cfg = load_sources(Path(args.config))
    if args.only:
        needle = args.only.lower()
        sources = [s for s in sources if needle in s.key.lower()]
        if not sources:
            print(f"no source matches {args.only!r}", file=sys.stderr)
            return 2

    print(f"auditing {len(sources)} source(s) from {args.config}")
    records = []
    for source in sources:
        record = await audit_one(source, args.timeout, args.retries)
        records.append(record)
        verdict = "OK  " if record["nodes"] else ("ERR " if record["note"] else "DEAD")
        protos = ", ".join(f"{k}:{v}" for k, v in record["protocols"].items())
        print(f"  [{verdict}] {record['name']:<30} "
              f"{record['bytes']:>9} B  {record['nodes']:>5} nodes  {protos}")
        if record["note"]:
            print(f"         note: {record['note']}")

    alive = [r for r in records if r["nodes"]]
    dead = [r for r in records if not r["nodes"]]
    print(f"\n{len(alive)}/{len(records)} sources yield nodes; "
          f"{len(dead)} yield nothing: {', '.join(r['name'] for r in dead) or 'none'}")

    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    # Exit 1 on any dead source: an empty pool is the failure this script exists
    # to catch, and a cron job cannot read stdout.
    return 1 if dead else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    parser.add_argument("--only", default="", help="substring match on the source name")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--json", default="", help="also write the records here")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
