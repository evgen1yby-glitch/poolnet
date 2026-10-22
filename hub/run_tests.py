#!/usr/bin/env python3
"""Run everything, offline. `python3 run_tests.py`.

The suite is deliberately hermetic: no test opens a socket. The two network
stages of the prober (the stage-1 TCP dial and the stage-2 verifying TLS
handshake) are injected as no-ops by `tests/test_prober.py`, and the pipeline
tests collapse them the same way. That is what keeps a run safe to execute on
a live server — it cannot touch the host network, change a route, or bind a
routable listener.

This wrapper exists so the suite can be run without pytest installed system
wide, and so a bare checkout gets a clear message instead of an ImportError.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

for entry in (str(ROOT), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

try:
    import pytest
except ImportError:  # pragma: no cover - bare checkout
    sys.exit(
        "pytest is not installed. Install the dev extras first:\n"
        "  python3 -m pip install -e '.[dev]'\n"
        "or run:  python3 -m pip install pytest pytest-asyncio"
    )

# `asyncio_mode = "auto"` comes from pyproject.toml; passing rootdir explicitly
# makes that config apply even when this script is invoked from elsewhere.
os.chdir(ROOT)


def main() -> int:
    args = sys.argv[1:] or ["tests", "-q"]
    print(f"hub: running pytest {' '.join(args)}")
    print(f"hub: rootdir {ROOT}")
    print("hub: no test opens a socket; both prober network stages are stubbed.\n")
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
