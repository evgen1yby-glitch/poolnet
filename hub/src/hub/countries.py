"""Country names for node labels, read from the page's own dictionary.

The landing page already carries the RU/EN tables it renders, in
`ui/hub.js` under `COUNTRY_NAMES`. A second Python copy would be a second
place for the two to disagree — the subscription would label a node
"Germany" while the card the visitor just clicked said "Германия", which
reads as a broken link rather than a translation.

So this parses the shipped bundle rather than restating it, and is
deliberately tolerant of not finding the table: the bundle is a static
asset, and the pipeline must still publish when the file has moved. The
fallback is the code itself, which is exactly what every client shows too.

This module exists separately from `bot.py` (which needs the same names)
because `bot.py` imports aiogram via `gate`, and the renderer must not
depend on a Telegram library being installed to label a node.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["country_name", "is_ru", "country_names"]


def is_ru() -> bool:
    """True when the active locale is Russian. Russian is the source language."""
    return os.environ.get("HUB_LOCALE", "ru").lower().startswith("ru")


#: Parsed once per process. The bundle changes only with a release and each
#: caller reads it a bounded number of times per run, so there is nothing to
#: invalidate.
_NAMES: dict[str, str] | None = None


def country_names() -> dict[str, str]:
    """`{"NL": "Нидерланды", ...}` in the active language, or `{}`."""
    global _NAMES
    if _NAMES is None:
        _NAMES = _parse_country_names()
    return _NAMES


def country_name(code: str) -> str:
    """Localised name for a two-letter code, or the code itself.

    The fallback is the code on purpose: every client shows the code when it
    has no name, so falling back to it is what a user already sees rather
    than a new kind of wrong.
    """
    return country_names().get((code or "").upper()) or (code or "").upper() or "Unknown"


def _parse_country_names() -> dict[str, str]:
    """Prefer the active language, then Russian, then English.

    Same order of preference as `countryName()` in the bundle, so a name is
    always one the visitor reads.
    """
    path = Path(__file__).resolve().parent / "ui" / "hub.js"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    block = text.split("COUNTRY_NAMES = {", 1)
    if len(block) < 2:
        return {}
    table = block[1]

    for lang in (("ru" if is_ru() else "en"), "ru", "en"):
        names = _names_from(table, lang)
        if names:
            return names
    return {}


def _names_from(table: str, lang: str) -> dict[str, str]:
    """One language block out of the `COUNTRY_NAMES` literal.

    Stopped at the block's closing brace rather than at the next language,
    because the fallback order means a missing `en:` must not silently read
    Russian's entries under the name "en". The block is flat — no nested
    braces inside it — so the first closing brace at the language's own
    indent is the end, and nothing after it can belong to it.
    """
    marker = f"{lang}: {{"
    start = table.find(marker)
    if start < 0:
        return {}
    body = table[start + len(marker):]
    end = body.find("\n    },")
    if end < 0:
        return {}
    names: dict[str, str] = {}
    # `CODE: "name"` per line. Character class rather than a stricter pattern:
    # the names contain spaces, hyphens and Cyrillic, and the only thing that
    # matters is that the value is quoted and the key is two ASCII letters.
    for match in re.finditer(r'([A-Za-z]{2}):\s*"([^"]+)"', body[:end]):
        names[match.group(1).upper()] = match.group(2)
    return names
