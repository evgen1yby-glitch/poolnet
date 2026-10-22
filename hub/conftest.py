"""Shared pytest configuration.

One rule: `src/` goes on `sys.path` here, once, instead of every test module
repeating the insertion in a comment-adjacent block. A module that imports
`hub.*` before this runs (collection order is alphabetical, so `test_api.py`
comes first) would otherwise fail with `ModuleNotFoundError`.

This also makes `from tests.factories import ...` work when pytest is launched
from a directory other than the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The project root is this file's own directory. Deriving it with `parents[1]`
# would be correct for a `tests/conftest.py`, but this file lives at the root —
# that off-by-one puts `/home` and `/home/src` on `sys.path`, neither of which
# contains the `hub` package, and the whole suite then fails at import.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

for path in (ROOT, SRC):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
