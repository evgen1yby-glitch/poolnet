"""The CLI surface: argument wiring, and the gate that keeps it off the network.

`main` is the one function an operator actually types, and it was almost entirely
untested — the subcommand list, the flags, and which flag is honoured by which
subcommand all sat behind a `parser.error("unknown command")` at the bottom.
That is how `audit-sources` was added and then removed with nothing noticing: a
typo in `choices` produces an argparse error at the operator's terminal, not in
the repo, and no suite in here ever called `main`.

Two properties are pinned here, and they are the two that fail silently:

1. **Every documented subcommand is in `choices` and dispatches.** A missing
   entry is an operator-facing usage error; a missing *dispatch* is worse, the
   command parses and then falls through to `parser.error`.
2. **`--allow-network` is off by default.** This is the safety gate. It is the
   difference between `hub run` reading source lists and `hub run` opening
   sockets on a host shared with another project's live traffic.

The tests go through `build_parser()` — extracted from `main` for exactly this
reason — because `argparse` gives no way to inspect a parser that has already
dispatched. `main` runs the command the moment `parse_args` returns, so
asserting on `main`'s namespace means running the command, and running the
command means touching the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub import cli  # noqa: E402


def test_every_subcommand_in_the_choices_list_dispatches():
    """`choices` and the dispatch chain must agree, entry for entry.

    A subcommand listed in `choices` that `main` does not handle parses fine and
    then dies in `parser.error("unknown command")` — a message that says the
    opposite of what happened, printed only after the operator has already typed
    a command the tool advertised. Pinned by reading the dispatch source, because
    that is the thing that can drift out of step with the literal list.
    """
    import inspect

    parser = cli.build_parser()
    actions = {a.dest: a for a in parser._actions}
    choices = actions["command"].choices

    dispatch = inspect.getsource(cli.main)
    undispatched = [c for c in choices if f'args.command == "{c}"' not in dispatch]
    assert not undispatched, (
        f"subcommand(s) {undispatched} are accepted by the parser but fall "
        "through to `parser.error`, so they are rejected with 'unknown command' "
        "after the operator has already typed one the tool advertised"
    )


def test_every_subcommand_documented_in_the_docstring_is_offered():
    """The docstring is the CLI's discoverable surface.

    `python -m hub --help` prints it. A command that works but is not in it is
    one nobody runs, and `audit-sources` — the subcommand that closes the
    silent source-rot loop — was exactly that.

    Checked in both directions, because the two failures look nothing alike and
    neither is caught by the other test:

    * documented but not offered — the operator reads about a command, types it,
      and gets a usage error;
    * offered but not documented — the command works and nobody knows it exists,
      which is the worse of the two because nothing reports the problem.

    The extraction splits on `python -m hub` rather than on whitespace, because
    the docstring's shape is `python -m hub serve # FastAPI ...` and the comment
    runs straight into the same line. Splitting on whitespace yields `-m` as a
    "command", which matches nothing and makes the test vacuous — hence the
    emptiness guard, which is what stopped that from passing silently.
    """
    parser = cli.build_parser()
    offered = {a.dest: a for a in parser._actions}["command"].choices

    documented = set()
    for line in cli.__doc__.splitlines():
        if "python -m hub" in line:
            tail = line.split("python -m hub", 1)[1].strip()
            documented.add(tail.split()[0].split("#")[0].strip())
    assert documented, "no commands were extracted from the docstring — the test is vacuous"

    missing = sorted(c for c in documented if c not in offered)
    assert not missing, f"documented but not offered: {missing}"
    undocumented = sorted(set(offered) - documented)
    assert not undocumented, (
        f"subcommand(s) {undocumented} work but are absent from the docstring, "
        "so nothing in `hub --help` tells anyone they exist"
    )


def test_audit_sources_is_a_real_subcommand():
    """Named explicitly, because this is the one that was lost.

    A subcommand whose absence from `choices` is caught by nothing is worse than
    one that was never written: `hub audit-sources` fails at the terminal, and
    the operator reasonably concludes the feature does not exist.
    """
    parser = cli.build_parser()
    choices = {a.dest: a for a in parser._actions}["command"].choices
    assert "audit-sources" in choices, choices


def test_allow_network_defaults_off():
    """The safety gate, asserted as a parsed default rather than as absence.

    `store_true` with `default=False` is the explicit spelling, and the
    distinction matters: a flag that defaulted to `None` would be falsy by luck
    and would read the same in every downstream `getattr(..., False)`, so a
    future change to `default=None` would pass any test that only checked
    "not args.allow_network". `is False` is what makes this a real assertion.
    """
    parser = cli.build_parser()
    assert parser.parse_args(["run"]).allow_network is False, (
        "--allow-network must default to off: `hub run` may not open sockets "
        "just because a driver happens to be present"
    )


def test_allow_network_can_be_turned_on():
    """The gate opens, which is what makes the default a decision.

    A flag that cannot be set is not a safety gate, it is a broken CLI — and a
    test that only pinned the default would leave that undetected. Paired with
    `test_allow_network_defaults_off`, the two together show the flag is wired
    rather than merely declared.
    """
    parser = cli.build_parser()
    assert parser.parse_args(["run", "--allow-network"]).allow_network is True


def test_allow_network_is_read_by_the_run_command():
    """Parsing a flag is not reading it.

    The failure mode `tests/test_pipeline.py` documents on the pipeline side,
    in its CLI form: `network=bool(getattr(args, "allow_network", False))` must
    actually reach the `Pipeline` it configures. If the plumbing were dropped,
    every test above would still pass and `hub run` would probe nothing.
    """
    import inspect

    source = inspect.getsource(cli)
    # The value is now bound to a local first, because the geo lookup gate needs
    # the same flag and reading it twice is how the two readings drift. What the
    # test must pin is that the flag reaches the `Pipeline`, not the spelling of
    # the expression that carries it.
    assert 'allow_network = bool(getattr(args, "allow_network", False))' in source, (
        "the run command no longer reads --allow-network"
    )
    assert "network=allow_network," in source, (
        "the run command is not passing --allow-network through to the pipeline"
    )


def test_an_unknown_command_is_a_usage_error():
    """Exit 2 with the usage message, which is argparse's contract.

    Pinned because a bare `parser.error` at the bottom of `main` returns 2 only
    by falling through an `if` chain — and a dispatch added *after* it silently
    becomes unreachable instead of failing.
    """
    import contextlib
    import io

    with pytest.raises(SystemExit) as exc:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(
            io.StringIO()
        ):
            cli.main(["definitely-not-a-command"])
    assert exc.value.code == 2, exc.value.code
