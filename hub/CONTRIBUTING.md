# Contributing

## The one rule that matters

**A change to behaviour needs a test that fails without it.** Not coverage for
its own sake — the specific test that would have caught the bug, or that pins
the property you are claiming. This repository has 475 of them and most exist
because something broke in a way nobody noticed until a user reported it weeks
later.

The comments are long here on purpose, and they are not decoration. Each one
records a decision that cost something: a measurement that contradicted the
obvious answer, a trap that produced a payload which looked correct and
connected nowhere, a trade made knowingly. When you change the code, change the
comment with it — a comment that describes the old behaviour is worse than no
comment, because the next reader trusts it.

## Getting set up

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m pytest tests/ -q
```

The suite is hermetic: **no test opens an external socket.** That is a
deliberate property, not an accident — see "Testing" below for what it means
for your change.

Optional, only if you touch the Xray dialect:

```sh
XRAY_BIN=/path/to/xray python -m pytest tests/test_renderer.py -q
```

## What this project is, in one paragraph

A control plane. It fetches publicly published proxy configurations, verifies
them through a staged funnel, scores what survives, and publishes the result as
ordinary client subscriptions. It **never relays user traffic** and there is no
code path that does. If your change would put the server in the data path, it
is out of scope — not because it is hard, but because the whole security posture
rests on the server consuming nodes exactly as an end user's device would.

## Where things live

| Path | What it is |
| --- | --- |
| `src/hub/pipeline.py` | The funnel: fetch → parse → probe → score → tier → render → publish |
| `src/hub/prober.py` | The staged verification (TCP, TLS, config, HTTP×2, speed) |
| `src/hub/renderer.py` | Three client dialects, one node model |
| `src/hub/api.py` | Read-only subscription service; reads files, never renders |
| `src/hub/models.py` | The node model and the rules about what a core can speak |
| `src/hub/store_state.py` | Node serialisation, so a verified node survives a round |
| `tests/` | The hermetic suite |

## Testing

**Do not add a test that needs the network.** If your change is about probing,
inject the seam: the pipeline takes `connect`, `handshake` and `driver_factory`
for exactly this, and the tests use them to collapse the network stages to
no-ops. A test that dials a real host is flaky on someone else's machine and
unusable in CI.

**Do not add a test that runs the real clock.** Time enters through arguments —
`now=`, an explicit `rotation`, an injected `time.monotonic` — so a test can
place itself anywhere in time without sleeping.

If your change genuinely cannot be tested hermetically, say so in the PR and
explain what you checked by hand. That is an acceptable answer; a test that
papers over the gap is not.

## Style

`ruff check src tests` must pass. Beyond that, the code follows the conventions
already in the file you are editing — read the neighbouring function before
writing yours. Two that are not obvious:

- **Comments explain *why*, not *what*.** The code says what it does. A comment
  earns its place by recording something the code cannot: why this value and
  not the obvious one, what was measured, what breaks otherwise.
- **Fail open, not closed, on publication.** A stage that fails keeps the
  previous generation. Serving a stale list is better than serving none, and
  the run report says what happened.

## Reporting a bug

Include the run report (`journalctl -u hub-probe.service`, or the output of
`hub run`) — it names every stage's survivor and error counts, which is usually
enough to tell a source problem from a pipeline one.

For anything security-related, see `SECURITY.md` instead. Do not open a public
issue.

## Pull requests

One concern per PR. A PR that fixes a bug and reformats a file will be asked to
split, because the reformat hides the fix in the diff.

In the description, say what you changed and **what you verified** — the command
you ran and what it printed. "Tests pass" is weaker than the actual count.
