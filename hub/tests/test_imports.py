"""Import-time tests. Cheap, and they catch the class of bug that makes every
other test file fail at collection with a confusing traceback.

The concrete case: `renderer.py` used `@dataclass(frozen=True)` without
importing `dataclass`. Because `from __future__ import annotations` turns
annotations into strings, the class *body* pastes fine — but the decorator is
evaluated eagerly, so the module raised `NameError` the instant anything
imported it. Every renderer test then failed at `from hub.renderer import ...`,
which looks like a test-harness problem rather than a missing import.

Two rules are pinned here:

1. every module in the package imports cleanly, in a fresh interpreter;
2. a module that defines a dataclass actually has the decorator in scope.

The second is checked without importing (so it works even if (1) fails), by
`ast`-parsing each file and confirming `dataclass` is imported whenever the
decorator is used.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "hub"

#: Modules whose module-level code pulls a third-party dependency. If that
#: dependency is not installed the module is expected to fail import, so the test
#: skips it rather than reporting a false defect. `pyproject.toml` declares these;
#: the skip only fires on a bare checkout without `pip install -e .`.
#: Every other module in the package is stdlib-only at import time, which is a
#: deliberate property: the pipeline, parser, and renderer must run on a box
#: with no FastAPI/aiogram installed.
OPTIONAL_DEPS = {
    "hub.api": ("fastapi",),
}

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _modules() -> list[str]:
    return sorted(
        f"hub.{path.stem}" for path in PACKAGE.glob("*.py") if path.stem != "__init__"
    )


def _deps_present(name: str) -> bool:
    import importlib.util

    return all(importlib.util.find_spec(dep) for dep in OPTIONAL_DEPS.get(name, ()))


def test_every_module_imports_cleanly():
    """A module that cannot import is a dead module, whatever it contains."""
    import os
    import subprocess

    # The subprocess must see the same `src/` the parent does: `-c` imports get
    # cwd and nothing else, so a bare `import hub.prober` fails with
    # ModuleNotFoundError even when the module is fine.
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    for name in _modules():
        if not _deps_present(name):
            continue
        # Import in a subprocess: a half-imported module left behind by an
        # earlier failure would mask the real error.
        result = subprocess.run(
            [sys.executable, "-c", f"import {name}"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 0, f"{name} failed to import:\n{result.stderr}"


def test_no_dataclass_decorator_without_its_import():
    """`@dataclass` is a decorator, so a missing import is a NameError at import.

    `from __future__ import annotations` hides this in the annotations but not
    in the decorator, which is why it is easy to write and fatal at runtime.
    """
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.asname or alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        } | {
            alias.asname or alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        uses_decorator = any(
            isinstance(node, ast.ClassDef)
            and any(
                (isinstance(d, ast.Name) and d.id == "dataclass")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass")
                for d in node.decorator_list
            )
            for node in ast.walk(tree)
        )
        if uses_decorator:
            assert "dataclass" in imported, (
                f"{path.name} uses @dataclass but never imports it"
            )
