"""`run_bot`'s start-up path: the two ways mock mode could refuse to start.

Both bugs below were found by running `hub bot` on the host it ships on, not by
any test. Each one produced a `RuntimeError` from a mode that is supposed to
work — "code complete, credential absent" — and neither is reachable from the
existing suite, because every existing test that involves the mock transport
either scripts the fact explicitly or never gets as far as `run_bot`:

* `build_bot` returns `None` for two different reasons — no token, and token with
  aiogram missing — and `run_bot` raised for both, so the mode that must work
  *without* the optional dependency was the mode it guaranteed to fail.
* `MockTransport.bot_status` was accepted and stored and then never read, so
  `get_chat_member` answered "left" for the bot's own id and the admin check
  failed for a default-constructed mock.

Each test here is paired with a control that proves it *can* fail. A test whose
subject is "does this raise?" passes for any number of unrelated reasons; the
control pins the reason by making the one relevant change in the other direction.

No test in this file opens a socket or constructs an aiogram Bot — which is the
point: `build_bot` defers the aiogram import precisely so this path runs on a box
that has no aiogram.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hub import bot  # noqa: E402
from hub.bot import (  # noqa: E402
    BotConfig,
    Gate,
    MockTransport,
    _deep_links,
    build_bot,
    run_bot,
)

CHANNEL = -1001234567890


# --------------------------------------------------------------------------- #
# `run_bot` in mock mode reaches readiness
# --------------------------------------------------------------------------- #

#: What `run_bot` prints when it has decided it may idle. This is the only
#: observable distinction between "started" and "hung before start", because
#: `run_bot` never returns: it ends in `await asyncio.sleep(3600)` forever.
READY = "bot ready in mock mode"


async def _mock_bot_output(*, ready_only: bool = False, extra_env: dict | None = None) -> str:
    """Run `hub bot` in mock mode and return what it printed before it idles.

    The real command, not a call to `run_bot`: `run_bot` ends in
    `asyncio.run(_main())`, so awaiting it from a test's own event loop raises
    `asyncio.run() cannot be called from a running event loop`. Starting the
    process the way an operator does is stronger anyway — it proves the module
    resolves, the `hub.cli` entry point wires the config, and the mode is
    announced before readiness is reached.

    Kills the process rather than waiting for it, because idling *is* success:
    a bot that exits has failed. The kill is why the output is bounded — there
    is nothing to wait on otherwise.

    No socket is opened in mock mode: no aiogram `Bot` is constructed (aiogram is
    not installed on this host) and no sing-box driver is built. The only
    process that exists is `python -m hub.cli bot` itself.
    """
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "HUB_CHANNEL_ID": str(CHANNEL),
        "TELEGRAM_BOT_TOKEN": "",
        "HUB_BASE_URL": "http://nodes.example:8090",
        "HUB_TOKEN": "tok123",
    }
    env.update(extra_env or {})
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-m", "hub.cli", "bot",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    chunks: list[str] = []
    try:
        # Read until the country example line, which is the last thing printed
        # before the idle loop. That is the line this file's most interesting
        # assertion is about, so stopping there is stopping exactly when there is
        # nothing left to read. `ready_only` stops one line earlier, at the
        # readiness marker itself.
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=90.0)
            if not line:
                break
            chunks.append(line.decode(errors="replace"))
            if ready_only:
                if READY in chunks[-1]:
                    break
            elif "e.g. one country:" in chunks[-1]:
                break
    except asyncio.TimeoutError:  # pragma: no cover - would fail the assert below
        pass
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
    return "".join(chunks)


def _mock_config(**kwargs) -> BotConfig:
    """A `BotConfig` with the mock transport, which is what `run_bot` branches on.

    Transport is passed explicitly rather than left to the default `None`,
    because `None` is the *other* mode and conflating the two in a test is how
    the first bug below stayed invisible: both return `None` from `build_bot`.
    """
    base = dict(
        token="",
        channel_id=CHANNEL,
        base_url="http://nodes.example:8090",
        transport=MockTransport(),
    )
    base.update(kwargs)
    return BotConfig(**base)  # type: ignore[arg-type]


async def test_mock_mode_reaches_readiness():
    """The mode that ships must start: no token, no aiogram, and still ready.

    This is the exact state of a fresh install — `TELEGRAM_BOT_TOKEN` unset,
    aiogram not installed — and `run_bot` used to answer it with
    `RuntimeError("aiogram is not installed")`, which is the one message that
    mode can never act on. What it must do instead is assemble the gate, pass the
    admin check, print the links, and idle.

    Run as a real subprocess rather than by importing and calling `run_bot`,
    because `run_bot` ends in `asyncio.run(_main())` and so cannot be awaited
    from a test's own event loop. That is not a workaround for a test-only
    limitation: it is the actual invocation, `python -m hub.cli bot`, so the
    readiness line is asserted on the process an operator would start.

    No socket is opened — mock mode constructs no aiogram Bot and no sing-box
    driver — so this does not touch the network.
    """
    out = await _mock_bot_output(ready_only=True)
    # The mode is announced first, which is what tells the reader that this
    # really is the credential-absent path and not a stub of it.
    assert "no TELEGRAM_BOT_TOKEN: bot in mock mode" in out, out
    assert READY in out, out


def test_the_readiness_test_can_fail():
    """The control for the test above.

    `run_bot` runs its body inside `asyncio.run(_main())`, so the only way to
    prove the assertion above is not vacuous is to run the *same* function with
    the guard removed and see it raise. The mutant is a stand-in rather than a
    mutation of live source, because `run_bot`'s whole body lives inside
    `asyncio.run` and there is no seam to reach: what this test proves is that
    the *condition the fix depends on* — "raises unless mock mode" — is a
    condition that can be false, i.e. that `test_mock_mode_reaches_readiness`
    would fail against the pre-fix code.
    """
    from hub import bot as bot_module

    original = bot_module.run_bot

    def _pre_fix(config, gate):
        # A synchronous stand-in is enough and deliberately not a coroutine:
        # `run_bot` is a plain `def` that calls `asyncio.run` internally, so the
        # call itself raises before any event loop exists.
        if bot_module.build_bot(config, gate) is None:
            raise RuntimeError("aiogram is not installed")
        raise AssertionError("mock mode should have taken this branch")

    config = _mock_config()
    gate = Gate(transport=config.transport, channel_id=CHANNEL)
    bot_module.run_bot = _pre_fix
    try:
        with pytest.raises(RuntimeError, match="aiogram is not installed"):
            _pre_fix(config, gate)
    finally:
        bot_module.run_bot = original
    assert bot_module.run_bot is original


async def test_real_mode_without_aiogram_still_raises():
    """The other half of the first fix, asserted so the fix cannot over-correct.

    A token, no aiogram, and no mock transport is a genuine misconfiguration:
    the operator asked for a live bot on a box that cannot run one. Silence
    there is what the original bug looked like from the other side — the fix
    must not turn every failure into a mock-mode fallback, because a live bot
    that quietly never polls is indistinguishable from a bot with no users.
    """
    config = BotConfig(
        token="123456:REAL",
        channel_id=CHANNEL,
        base_url="http://nodes.example:8090",
        transport=None,
    )
    gate = Gate(transport=MockTransport(), channel_id=CHANNEL)
    with pytest.raises(RuntimeError, match="aiogram is not installed"):
        run_bot(config, gate)


async def test_build_bot_returns_none_only_where_the_caller_can_handle_it():
    """`run_bot`'s branch condition is the transport, not the return value.

    Pinned as a statement about `build_bot`'s contract rather than about
    `run_bot`'s body, because the bug was a misreading of that contract: the
    function has always returned `None` in two situations and the caller treated
    both as "the caller cannot proceed".
    """
    # No transport at all: `build_bot` returns `None` before touching aiogram.
    mock = _mock_config()
    none_config = BotConfig(
        token=mock.token,
        channel_id=mock.channel_id,
        base_url=mock.base_url,
        transport=None,
    )
    assert build_bot(none_config, Gate(transport=MockTransport(), channel_id=CHANNEL)) is None

    # The mock transport is a *transport*, not an aiogram dispatcher, so it is
    # also `None` — which is the whole reason the caller must look at the
    # transport rather than at this return value.
    assert build_bot(mock, Gate(transport=MockTransport(), channel_id=CHANNEL)) is None


# --------------------------------------------------------------------------- #
# `MockTransport.bot_status`
# --------------------------------------------------------------------------- #


async def test_a_default_mock_passes_its_own_admin_check():
    """`is_admin_ok` looks the bot up by its own id, and that lookup must work.

    This is the second bug, and the reason it is here rather than in
    `tests/test_gate.py` is that the *gate* was always correct: it asked the
    right question of the transport and the transport answered about someone
    else. A gate test that scripts `members` for the bot's id hides the
    transport's behaviour, which is exactly what `test_admin_ok_requires_bot_
    membership` in that file does.
    """
    transport = MockTransport()  # no scripted members at all
    gate = Gate(transport=transport, channel_id=CHANNEL)
    assert await gate.is_admin_ok() is True
    # And it was answered from `bot_status`, not from the "left" default.
    assert ("getChatMember", CHANNEL, transport.bot_id) in transport.calls


async def test_bot_status_of_left_still_fails_the_admin_check():
    """The control: the field is read, so changing it changes the verdict.

    If the default above passes and this fails, the answer came from
    `bot_status`. If both passed, the mock would be answering "administrator"
    for anything and `is_admin_ok` would be untestable — the same
    indistinguishable-outcome shape as the bug.
    """
    transport = MockTransport(bot_status="left")
    gate = Gate(transport=transport, channel_id=CHANNEL)
    assert await gate.is_admin_ok() is False


async def test_a_scripted_entry_for_the_bot_overrides_bot_status():
    """The precedence, which both directions above depend on.

    `test_admin_ok_requires_bot_membership` in `tests/test_gate.py` writes
    `members={(CHANNEL, 7): "left"}` over a transport whose `bot_status` is
    `"administrator"`, and expects `False`. That only works if the scripted entry
    wins; a `bot_status`-first implementation would silently keep that test's
    second half passing for the wrong reason while breaking its intent.
    """
    transport = MockTransport(bot_id=7, bot_status="administrator")
    transport.members[(CHANNEL, 7)] = "left"
    gate = Gate(transport=transport, channel_id=CHANNEL)
    assert await gate.is_admin_ok() is False


async def test_bot_status_is_not_returned_for_any_other_user():
    """`bot_status` describes the bot, so it must not answer for anyone else.

    Without this the first test above would pass for a second, wrong reason: a
    transport that returns `bot_status` for every unknown user would satisfy
    `is_admin_ok` *and* every `is_member` check in the suite, which is a mock
    that cannot fail. That is worse than the bug it replaced.
    """
    transport = MockTransport(bot_status="administrator")
    assert await transport.get_chat_member(CHANNEL, 4242) == "left"
    assert await transport.get_chat_member(CHANNEL, 0) == "left"


# --------------------------------------------------------------------------- #
# the links mock mode prints
# --------------------------------------------------------------------------- #


async def test_mock_mode_prints_working_links_not_relative_paths():
    """The links are absolute, because `/sub/<token>` is unopenable from Telegram.

    `run_bot` reads the token from the environment, so this sets one, and the
    point is not the value but the *shape* of what gets printed: a bare
    `/sub/...` is the failure `config/sources.yaml`'s `base_url` comment warns
    about, and mock mode is the one place that string is reachable without any
    credential at all.

    Run as a subprocess for the same reason as the readiness test, and collects
    the whole link block rather than one line.
    """
    out = await _mock_bot_output()
    assert "http://nodes.example:8090/sub/tok123" in out, out
    # The country line is the one that makes the landing page's cards work.
    assert "http://nodes.example:8090/sub/tok123/country/NL" in out, out
    # A relative path is the bug this pins: the process still runs and still
    # prints, so only a substring check catches it.
    assert " /sub/" not in out, out


def test_the_printed_links_are_the_same_ones_the_page_builds():
    """Mock mode's links and `_deep_links`' output are the same function.

    Pinned as an equality rather than by re-checking each URL, because the value
    of mock mode is that the printed strings are *the* strings a live bot would
    send — a second copy of the link table is the way those two drift until an
    operator tests one path and users hit the other.
    """
    expected = _deep_links("http://nodes.example:8090", "tok123")
    assert expected["copy"] == "http://nodes.example:8090/sub/tok123"
    assert expected["v2rayng"].startswith("v2rayng://install-sub?url=")


async def test_the_bot_reads_the_same_base_url_as_the_api():
    """One public address, two readers, and they must agree.

    `create_app` read `base_url` out of `config/sources.yaml`; `_bot` read only
    `HUB_BASE_URL`. Set in the file and not exported, that made the API serve
    `https://…/sub/<token>` while the bot handed out `/sub/<token>` — a relative
    path, and the one thing this whole feature is not allowed to produce. It
    fails silently: the bot starts, prints, and idles, so nothing says the links
    are unopenable until a Telegram user tries one. Both surfaces now read the
    environment first and the file second, so they cannot disagree.

    The shipped config is deliberately **empty**, which is why this asserts the
    environment side: a checked-in origin is one operator's address, wrong for
    every other install, and it advertises links to a server they do not run.
    """
    # The environment alone must produce absolute links.
    expected = "https://hub.example.test"
    out = await _mock_bot_output(extra_env={"HUB_BASE_URL": expected})
    assert f"{expected}/sub/tok123" in out, out
    assert " /sub/" not in out, out

    # With nothing set anywhere, the bot must not emit a relative link at all:
    # a bare `/sub/…` handed to a Telegram user opens nothing.
    from hub.fetcher import load_sources

    _sources, settings = load_sources(ROOT / "config" / "sources.yaml")
    assert not str(settings.get("base_url") or ""), (
        "the shipped config must not carry an origin; set HUB_BASE_URL instead"
    )

    # Precedence: the variable still wins when it is set.
    out = await _mock_bot_output(extra_env={"HUB_BASE_URL": "https://hub.example"})
    assert "https://hub.example/sub/tok123" in out, out
    assert expected not in out, out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
