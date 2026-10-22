"""The `check-parser` fixture is a contract, so it gets a test.

`cli._check_parser` reads `tests/fixtures/valid_uris.txt` and fails loudly if any
line does not parse. That command is only run when an operator remembers to, so
the same guarantee is asserted here: every non-comment line in that file must
parse without an error, and must produce a node whose protocol matches its
scheme.

The inverse fixture (`malformed_uris.txt`, if present) must produce an error for
every line — a "bad input" file where the parser silently succeeds is worse than
no file at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.parser import parse_one  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VALID = FIXTURES / "valid_uris.txt"
MALFORMED = FIXTURES / "malformed_uris.txt"


def _meaningful_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_valid_fixture_exists():
    assert VALID.is_file(), "check-parser needs tests/fixtures/valid_uris.txt"


#: Schemes that intentionally map onto a different Protocol. `socks4`/`socks5`
#: are one protocol with version markers, and an `https://` share link is an
#: HTTP proxy speaking TLS — the protocol is still HTTP.
SCHEME_ALIASES = {
    "socks": "socks",
    "socks5": "socks",
    "socks4": "socks",
    "http": "http",
    "https": "http",
    "hy2": "hysteria2",
    "ss": "ss",
}


def _expected_protocol(scheme: str) -> str:
    return SCHEME_ALIASES.get(scheme, scheme)


def test_every_valid_line_parses():
    for line in _meaningful_lines(VALID):
        node, error = parse_one(line)
        assert error is None, f"{line[:70]!r} was rejected: {error}"
        assert node is not None
        # The scheme in the URI and the protocol in the node must agree, or the
        # renderer emits a URI this node cannot actually run.
        scheme = line.split("://", 1)[0].lower()
        assert node.protocol.value == _expected_protocol(scheme), line


def test_every_malformed_line_is_rejected():
    if not MALFORMED.is_file():
        return
    for line in _meaningful_lines(MALFORMED):
        node, error = parse_one(line)
        assert error is not None, f"{line[:70]!r} unexpectedly parsed"
        assert node is None, "parse_one must never return both a node and an error"


def test_the_fixture_is_not_empty():
    # An empty file makes `check-parser` a green no-op that proves nothing.
    assert len(_meaningful_lines(VALID)) >= 10
